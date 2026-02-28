# Setup Guide - Balance Sheet Generator

## 🚀 Complete Setup Instructions

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
```bash
cp .env.example .env
```

Edit `.env` with your QuickBooks credentials:

```env
# QuickBooks Online OAuth Configuration
QBO_CLIENT_ID=your_qbo_client_id_here
QBO_CLIENT_SECRET=your_qbo_client_secret_here
QBO_ENVIRONMENT=sandbox
QBO_REDIRECT_URI=http://localhost:5000/callback

# Flask Secret Key
SECRET_KEY=your-secret-key-here-generate-a-new-one

# Encryption Key for token storage
ENCRYPTION_KEY=your-encryption-key-here-generate-a-new-one
```

### 3. Generate Required Keys

#### Flask Secret Key
```bash
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
```

#### Encryption Key
```bash
python -c "from cryptography.fernet import Fernet; print('ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
```

### 4. QuickBooks Developer Setup

1. **Create QuickBooks App**
   - Go to [QuickBooks Developer Portal](https://developer.intuit.com/)
   - Click "Create App"
   - Select "QuickBooks Online and Payments"
   - Choose "Production" or "Sandbox"

2. **Configure OAuth2**
   - Set Redirect URI: `http://localhost:5000/callback`
   - Add required scopes:
     - `com.intuit.quickbooks.accounting`
     - `openid`
     - `profile`
     - `email`

3. **Get Credentials**
   - Copy Client ID and Client Secret
   - Add to your `.env` file

### 5. Initialize Database
```bash
python -c "from app import init_db; init_db()"
```

### 6. Run Application
```bash
python app.py
```

Visit `http://localhost:5000` to access the application.

## 🔧 Testing with Sandbox

1. Set `QBO_ENVIRONMENT=sandbox` in `.env`
2. Use QuickBooks Sandbox credentials
3. Test with sample data provided

## 🌐 Production Deployment

1. Set `QBO_ENVIRONMENT=production`
2. Use production QuickBooks app credentials
3. Configure HTTPS (required for production)
4. Set proper redirect URI
5. Generate new encryption keys

## 🐛 Common Issues & Solutions

### Connection Issues
- **Problem**: "Connection failed" error
- **Solution**: Check Client ID/Secret, redirect URI, and environment

### Token Issues
- **Problem**: "Token expired" errors
- **Solution**: Application handles auto-refresh, reconnect if persistent

### Database Issues
- **Problem**: Database errors
- **Solution**: Delete `instance/balance_sheet_pro.db` and reinitialize

### Import Errors
- **Problem**: Module not found errors
- **Solution**: Ensure all requirements installed: `pip install -r requirements.txt`

## 📞 Support

For issues:
1. Check application logs: `balance_sheet_app.log`
2. Verify all environment variables are set
3. Ensure QuickBooks app is properly configured
4. Review this setup guide

## ✅ Verification Checklist

- [ ] Python 3.11+ installed
- [ ] All dependencies installed
- [ ] `.env` file configured
- [ ] QuickBooks app created
- [ ] OAuth2 properly configured
- [ ] Database initialized
- [ ] Application runs without errors
- [ ] Can connect to QuickBooks
- [ ] Balance sheet generation works
- [ ] PDF/Excel exports function
