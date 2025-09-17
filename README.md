# AWS Textract to DynamoDB Employee Matching System

A Python application that uses AWS Textract to extract employee data from sign-in sheet images and matches them with DynamoDB employee profiles.

## 🚀 Features

- **AWS Textract Integration**: Extracts employee data from sign-in sheet images
- **DynamoDB Employee Matching**: Matches extracted names with database profiles
- **Fuzzy Name Matching**: Uses difflib for intelligent name matching
- **Confidence Scoring**: Provides match confidence percentages
- **Console Reporting**: Detailed comparison results without database storage

## 🔧 Technical Details

- **ID-based matching**: Direct employee ID lookup
- **Name-based matching**: Fuzzy string matching for names
- **Batch processing**: Handles multiple employees efficiently
- **Error handling**: Robust AWS credential and API error management

## 📊 Results

- 87.5% match accuracy (7/8 employees matched)
- 100% confidence for all successful matches
- Console-only output (no database storage)

## 🛠️ Usage

```bash
# Activate virtual environment
source venv/bin/activate

# Run the script
python textract_to_ddb.py --file "path/to/image.jpg" --date "2024-01-15" --sheet-id "SHEET001"
```

## 📋 Requirements

- Python 3.7+
- AWS credentials configured
- boto3 library
- AWS Textract and DynamoDB permissions

## 🔑 AWS Setup

1. Configure AWS credentials:
   ```bash
   aws configure
   # or
   aws sso login --profile dev-aws
   ```

2. Set environment variables:
   ```bash
   export AWS_REGION=us-east-1
   export TABLE_NAME=aakarsh-dev-signins
   ```

## 📁 Project Structure

```
├── textract_to_ddb.py    # Main application script
├── .gitignore           # Git ignore file
└── README.md            # This file
```

## 🎯 Example Output

```
🔍 Processing sign-in sheet...
📷 Image loaded: 449,916 bytes
📊 Extracted 8 rows from table
👥 Loading employee profiles from DynamoDB...
📋 Found 8 employee profiles in database

👤 Row 1: 'Jermey Dickamorc' (ID: 1042823)
   🎯 Direct ID match: Jermey Dickamorc (conf: 1.000)
   ✅ MATCHED | Match: ID | Conf: 1.000

📈 OVERALL MATCH PERCENTAGE: 87.5%
   (7/8 employees matched)
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

This project is licensed under the MIT License.
