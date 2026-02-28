# Balance Sheet Application

A Flask-based web application for managing and exporting summary-level balance sheets with reconciliation notes.

## Features

### QuickBooks Online Integration
- **OAuth2 Authentication**: Secure connection with automatic token refresh
- **Real-time Data**: Pulls Trial Balance, Balance Sheet, Chart of Accounts, A/R, A/P, and bank balances
- **Token Security**: Encrypted storage of access and refresh tokens

### Comprehensive Reconciliation
- **Trial Balance Validation**: Ensures debits equal credits
- **Balance Sheet Verification**: Validates Assets = Liabilities + Equity
- **Account Balance Checks**: Flags unusual negative balances
- **Bank Reconciliation**: Compares bank vs ledger balances
- **Open Items Analysis**: Identifies unreconciled receivables and payables
- **Retained Earnings Validation**: Verifies equity calculations

### Professional Reports
- **Summary Balance Sheet**: Clean, categorized presentation
- **PDF Export**: Professional layout with company branding
- **Excel Export**: Multi-sheet workbook with detailed data
- **Adjustment Notes**: Comprehensive reconciliation documentation

### Modern Web Interface
- **Responsive Design**: Works on desktop and mobile
- **Real-time Status**: Live connection status and progress indicators
- **Interactive Dashboard**: Easy-to-use balance sheet generation
- **Bootstrap Styling**: Clean, professional UI

### Audit & Logging
- **Comprehensive Audit Trail**: Logs all user actions and system events
- **Error Tracking**: Detailed error logging for troubleshooting
- **IP & User Agent Tracking**: Security monitoring
- **File-based Logs**: Persistent audit records

## Quick Start

### Prerequisites
- Python 3.11+
- QuickBooks Developer Account
- QuickBooks App with OAuth2 enabled

### Installation

1. **Clone and Setup**

### Accounts Table
- `id`: Primary key
- `name`: Account name
- `account_type`: 'asset', 'liability', or 'equity'
- `subcategory`: 'current' or 'non_current' (for assets/liabilities)
- `balance`: Current balance
- `status`: 'reconciled', 'pending', 'adjusted', or 'open_item'
- `description`: Optional description

### Reconciliation Notes Table
- `id`: Primary key
- `title`: Note title
- `description`: Detailed description
- `amount`: Adjustment amount
- `note_type`: 'adjustment', 'open_item', or 'info'
- `status`: 'pending', 'resolved', or 'reviewed'

## Sample Data

The application includes sample data demonstrating:
- **Assets**: Cash, accounts receivable, inventory, prepaid expenses, property & equipment, intangible assets
- **Liabilities**: Accounts payable, accrued liabilities, short-term debt, long-term debt
- **Equity**: Common stock, retained earnings, current period net income
- **Reconciliation Notes**: Inventory adjustment, short-term debt item, net income reclassification, intangible assets review

## Export Features

### PDF Export
- Professional formatting with proper balance sheet layout
- Clear section headers (Assets, Liabilities, Equity)
- Currency formatting
- Automatic date stamping

### Excel Export
- Two worksheets: Balance Sheet and Reconciliation Notes
- Formatted with proper headers and styling
- Currency formatting for all monetary values
- Detailed reconciliation notes with status tracking

## Usage

1. **View Balance Sheet**: The main dashboard shows the summary balance sheet with real-time data
2. **Review Reconciliation Notes**: Check the right panel for any items requiring attention
3. **Export Reports**: Use the Quick Actions panel to generate PDF or Excel reports
4. **Manage Data**: Use the API endpoints to programmatically update accounts and notes

## Development

### Adding New Features

1. **Database Changes**: Modify the models in `app.py`
2. **API Endpoints**: Add new routes in `app.py`
3. **Frontend Updates**: Modify `templates/index.html` and add JavaScript functions

### Database Reset

To reset the database with fresh sample data:
```bash
rm balance_sheet.db
python app.py
```

## Security Notes

- This application is intended for internal use
- SQLite database file should be secured appropriately
- No authentication is implemented (add as needed for production)
- API endpoints accept data without validation in this demo version

## Support

For questions or issues with the application:
1. Check the browser console for JavaScript errors
2. Review the Flask application logs
3. Verify all dependencies are installed correctly

## Future Enhancements

- User authentication and authorization
- QuickBooks Online integration
- Advanced filtering and reporting
- Historical data tracking
- Multi-currency support
- Automated reconciliation suggestions
