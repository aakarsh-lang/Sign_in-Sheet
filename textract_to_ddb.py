import os, json, argparse, difflib, boto3
from typing import Any, Dict, List, Optional
from decimal import Decimal

REGION = os.getenv("AWS_REGION", "us-east-1")
TABLE  = os.getenv("TABLE_NAME", "aakarsh-dev-signins")

# Use AWS profile if available
import boto3.session
session = boto3.session.Session(profile_name='dev-aws') if os.getenv('AWS_PROFILE') == 'dev-aws' else boto3.session.Session()
textract = session.client("textract", region_name=REGION)
ddb = session.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE)

def _text_from(block: Dict[str, Any], idmap: Dict[str, Dict[str, Any]]) -> str:
    out: List[str] = []
    for rel in block.get("Relationships", []):
        if rel.get("Type") == "CHILD":
            for cid in rel.get("Ids", []):
                wb = idmap.get(cid)
                if not wb: 
                    continue
                if wb.get("BlockType") == "WORD":
                    out.append(wb.get("Text", ""))
                elif wb.get("BlockType") == "SELECTION_ELEMENT" and wb.get("SelectionStatus") == "SELECTED":
                    out.append("[X]")  # plain ASCII marker
    return " ".join([t for t in out if t]).strip()

def parse_first_table(blocks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Return list of row dicts from the first detected table."""
    idmap = {blk.get("Id"): blk for blk in blocks if "Id" in blk}
    table_blk = next((blk for blk in blocks if blk.get("BlockType") == "TABLE"), None)
    if not table_blk:
        return []

    cells: Dict[tuple, str] = {}
    rmax = cmax = 0
    for rel in table_blk.get("Relationships", []):
        if rel.get("Type") == "CHILD":
            for cid in rel.get("Ids", []):
                cell = idmap.get(cid)
                if not cell or cell.get("BlockType") != "CELL":
                    continue
                r = int(cell.get("RowIndex", 0)); c = int(cell.get("ColumnIndex", 0))
                rmax, cmax = max(rmax, r), max(cmax, c)
                cells[(r, c)] = _text_from(cell, idmap)

    # header from row 1
    header: List[str] = []
    for c in range(1, cmax + 1):
        h_raw = (cells.get((1, c)) or f"Col{c}").strip().lower()
        if "name" in h_raw: header.append("Name")
        elif "employee" in h_raw and "id" in h_raw: header.append("EmployeeID")
        elif "room" in h_raw: header.append("RoomNumber")
        elif "wake" in h_raw: header.append("Wake")
        elif "sign" in h_raw: header.append("Signature")
        else: header.append(h_raw.replace(" ", ""))

    # data rows
    out_rows: List[Dict[str, str]] = []
    for r in range(2, rmax + 1):
        row: Dict[str, str] = {}
        empty = True
        for ci, key in enumerate(header, start=1):
            val = (cells.get((r, ci)) or "").strip()
            if val: empty = False
            row[key] = val
        if not empty:
            out_rows.append(row)
    return out_rows

def get_profile(emp_id: str) -> Optional[Dict[str, Any]]:
    try:
        res = table.get_item(Key={"PK": f"EMP#{emp_id}", "SK": "PROFILE"})
        return res.get("Item")
    except Exception:
        return None

def sim(a: Optional[str], b: Optional[str]) -> float:
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0

def get_all_employee_profiles() -> Dict[str, Dict[str, Any]]:
    """Get all employee profiles from DynamoDB"""
    try:
        response = table.scan(
            FilterExpression="begins_with(PK, :pk_prefix)",
            ExpressionAttributeValues={":pk_prefix": "EMP#"}
        )
        profiles = {}
        for item in response.get("Items", []):
            if item.get("SK") == "PROFILE":
                emp_id = item.get("PK", "").replace("EMP#", "")
                profiles[emp_id] = item
        return profiles
    except Exception as e:
        print(f"❌ Error fetching employee profiles: {e}")
        return {}

def find_best_match(textract_name: str, profiles: Dict[str, Dict[str, Any]]) -> tuple:
    """Find the best matching employee profile for a given name"""
    if not textract_name.strip():
        return None, 0.0
    
    best_match = None
    best_confidence = 0.0
    
    for emp_id, profile in profiles.items():
        db_name = profile.get("Name", "")
        confidence = sim(textract_name, db_name)
        
        if confidence > best_confidence:
            best_confidence = confidence
            best_match = {"emp_id": emp_id, "name": db_name, "profile": profile}
    
    return best_match, best_confidence

def process(file_path: str, sheet_date: str, sheet_id: str = "") -> None:
    print("🔍 Processing sign-in sheet...")
    print("=" * 60)
    
    # Load image and process with Textract
    with open(file_path, "rb") as f:
        img = f.read()
    print(f"📷 Image loaded: {len(img):,} bytes")
    
    resp = textract.analyze_document(Document={"Bytes": img}, FeatureTypes=["TABLES"])
    rows = parse_first_table(resp.get("Blocks", []))
    print(f"📊 Extracted {len(rows)} rows from table")
    
    # Get all employee profiles for matching
    print("👥 Loading employee profiles from DynamoDB...")
    all_profiles = get_all_employee_profiles()
    print(f"📋 Found {len(all_profiles)} employee profiles in database")
    
    # Track matches and extra names
    matched_employees = set()
    processed_records = []
    extra_names = []
    
    print("\n🔄 Processing each employee...")
    print("-" * 60)
    
    for i, r in enumerate(rows, 1):
        textract_name = (r.get("Name") or "").strip()
        emp_id = (r.get("EmployeeID") or "").replace(" ", "").strip()
        
        print(f"\n👤 Row {i}: '{textract_name}' (ID: {emp_id})")
        
        # Try direct ID match first
        direct_match = None
        direct_confidence = 0.0
        
        if emp_id and emp_id in all_profiles:
            direct_match = all_profiles[emp_id]
            direct_confidence = sim(textract_name, direct_match.get("Name", ""))
            print(f"   🎯 Direct ID match: {direct_match.get('Name', '')} (conf: {direct_confidence:.3f})")
        
        # Try name-based matching
        name_match, name_confidence = find_best_match(textract_name, all_profiles)
        
        # Choose the best match
        if direct_confidence >= name_confidence and direct_confidence > 0.5:
            # Use direct ID match
            matched_profile = direct_match
            confidence = direct_confidence
            match_type = "ID"
            matched_emp_id = emp_id
        elif name_confidence > 0.5:
            # Use name match
            matched_profile = name_match["profile"]
            confidence = name_confidence
            match_type = "NAME"
            matched_emp_id = name_match["emp_id"]
            print(f"   🔍 Name match: {name_match['name']} (ID: {matched_emp_id}, conf: {confidence:.3f})")
        else:
            # No good match found
            matched_profile = None
            confidence = 0.0
            match_type = "NONE"
            matched_emp_id = emp_id or "UNKNOWN"
            print(f"   ❌ No match found (best: {name_confidence:.3f})")
            if textract_name:
                extra_names.append(textract_name)
        
        # Determine if valid
        valid = bool(matched_profile) and confidence >= 0.90
        
        # Track matched employees
        if matched_profile:
            matched_employees.add(matched_emp_id)
        
        # Create record
        item = {
            "PK": f"EMP#{matched_emp_id}",
            "SK": f"SIGNIN#{sheet_date}",
            "EmployeeID": matched_emp_id,
            "Name": textract_name,
            "SheetDate": sheet_date,
            "RoomNumber": r.get("RoomNumber", ""),
            "Wake": r.get("Wake", ""),
            "SignaturePresent": bool(r.get("Signature")),
            "SheetId": sheet_id,
            "Validation": {
                "valid": valid,
                "confidence": Decimal(str(round(confidence, 3))),
                "matchedName": matched_profile.get("Name", "") if matched_profile else "",
                "matchType": match_type
            }
        }
        
        # Display results (comparison only, no storage)
        status = "✅ MATCHED" if valid else "⚠️  LOW CONF" if confidence > 0 else "❌ NO MATCH"
        print(f"   {status} | Match: {match_type} | Conf: {confidence:.3f}")
        
        processed_records.append({
            "row": i,
            "textract_name": textract_name,
            "emp_id": emp_id,
            "matched_emp_id": matched_emp_id,
            "matched_name": matched_profile.get("Name", "") if matched_profile else "",
            "confidence": confidence,
            "match_type": match_type,
            "valid": valid
        })
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 PROCESSING SUMMARY")
    print("=" * 60)
    
    total_rows = len(rows)
    valid_matches = sum(1 for r in processed_records if r["valid"])
    high_conf_matches = sum(1 for r in processed_records if r["confidence"] >= 0.8)
    id_matches = sum(1 for r in processed_records if r["match_type"] == "ID")
    name_matches = sum(1 for r in processed_records if r["match_type"] == "NAME")
    no_matches = sum(1 for r in processed_records if r["match_type"] == "NONE")
    
    print(f"📋 Total rows processed: {total_rows}")
    print(f"✅ Valid matches (≥90%): {valid_matches}")
    print(f"🎯 High confidence (≥80%): {high_conf_matches}")
    print(f"🆔 ID-based matches: {id_matches}")
    print(f"📝 Name-based matches: {name_matches}")
    print(f"❌ No matches: {no_matches}")
    print(f"👥 Unique employees matched: {len(matched_employees)}")
    print(f"💾 Data storage: DISABLED (comparison only)")
    
    # Display all employees in array format for easy comparison
    print("\n" + "=" * 60)
    print("📋 EMPLOYEE COMPARISON ARRAYS")
    print("=" * 60)
    
    # Textract employees (from sign-in sheet)
    textract_employees = []
    for record in processed_records:
        if record["textract_name"].strip():
            textract_employees.append({
                "id": record["emp_id"],
                "name": record["textract_name"],
                "match_type": record["match_type"],
                "confidence": record["confidence"],
                "matched_name": record["matched_name"]
            })
    
    print("\n🔍 EMPLOYEES FROM SIGN-IN SHEET:")
    print("[" + ", ".join([f'{{"id": "{emp["id"]}", "name": "{emp["name"]}", "match": "{emp["match_type"]}", "conf": {emp["confidence"]:.3f}, "matched": "{emp["matched_name"]}"}}' for emp in textract_employees]) + "]")
    
    # Database employees (all profiles)
    db_employees = []
    for emp_id, profile in all_profiles.items():
        db_employees.append({
            "id": emp_id,
            "name": profile.get("Name", "Unknown")
        })
    
    print("\n💾 EMPLOYEES IN DATABASE:")
    print("[" + ", ".join([f'{{"id": "{emp["id"]}", "name": "{emp["name"]}"}}' for emp in db_employees]) + "]")
    
    # Matched employees (successful matches)
    matched_employee_details = []
    for record in processed_records:
        if record["match_type"] != "NONE" and record["confidence"] > 0:
            matched_employee_details.append({
                "textract_id": record["emp_id"],
                "textract_name": record["textract_name"],
                "db_id": record["matched_emp_id"],
                "db_name": record["matched_name"],
                "match_type": record["match_type"],
                "confidence": record["confidence"]
            })
    
    print("\n✅ SUCCESSFUL MATCHES:")
    if matched_employee_details:
        print("[" + ", ".join([f'{{"textract": {{"id": "{emp["textract_id"]}", "name": "{emp["textract_name"]}"}}, "db": {{"id": "{emp["db_id"]}", "name": "{emp["db_name"]}"}}, "type": "{emp["match_type"]}", "conf": {emp["confidence"]:.3f}}}' for emp in matched_employee_details]) + "]")
    else:
        print("[]")
    
    # Extra names (in sign-in sheet but not in DB)
    if extra_names:
        print(f"\n⚠️  EXTRA NAMES (in sign-in sheet but not in database):")
        extra_array = [f'{{"name": "{name}"}}' for name in extra_names]
        print("[" + ", ".join(extra_array) + "]")
    else:
        print(f"\n✅ All names found in database")
    
    # Unmatched employees (in DB but not in sign-in sheet)
    unmatched_employees = set(all_profiles.keys()) - matched_employees
    if unmatched_employees:
        print(f"\n👥 EMPLOYEES NOT IN SIGN-IN SHEET ({len(unmatched_employees)}):")
        unmatched_array = [f'{{"id": "{emp_id}", "name": "{all_profiles[emp_id].get("Name", "Unknown")}"}}' for emp_id in sorted(unmatched_employees)]
        print("[" + ", ".join(unmatched_array) + "]")
    
    # Calculate overall match percentage
    overall_match_pct = (len(matched_employees) / len(all_profiles)) * 100 if all_profiles else 0
    print(f"\n📈 OVERALL MATCH PERCENTAGE: {overall_match_pct:.1f}%")
    print(f"   ({len(matched_employees)}/{len(all_profiles)} employees matched)")
    
    print("\n🎉 Processing complete!")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="Path to local sign-in image (jpg/png)")
    ap.add_argument("--date", required=True, help="Sheet date YYYY-MM-DD")
    ap.add_argument("--sheet-id", default="", help="Optional ID printed on the sheet")
    args = ap.parse_args()
    process(args.file, args.date, args.sheet_id)
