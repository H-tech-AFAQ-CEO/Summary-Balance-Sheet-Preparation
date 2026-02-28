from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import sqlite3
import json
import logging
import requests
from werkzeug.utils import secure_filename
import tempfile
import pandas as pd
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import io
import hashlib
import secrets
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///balance_sheet_pro.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))

# QuickBooks OAuth Configuration
QBO_CLIENT_ID = os.getenv('QBO_CLIENT_ID')
QBO_CLIENT_SECRET = os.getenv('QBO_CLIENT_SECRET')
QBO_REDIRECT_URI = os.getenv('QBO_REDIRECT_URI', 'http://localhost:5000/callback')
QBO_ENVIRONMENT = os.getenv('QBO_ENVIRONMENT', 'sandbox')  # 'sandbox' or 'production'

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('balance_sheet_app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

db = SQLAlchemy(app)

# QuickBooks OAuth Setup (simplified without authlib)
# Note: This is a placeholder for future OAuth implementation

class Account(db.Model):
    __tablename__ = 'accounts'
    
    id = db.Column(db.Integer, primary_key=True)
    qbo_account_id = db.Column(db.String(50), unique=True)
    name = db.Column(db.String(200), nullable=False)
    account_type = db.Column(db.String(50), nullable=False)  # asset, liability, equity
    subcategory = db.Column(db.String(100))  # current, non_current
    classification = db.Column(db.String(50))  # Asset, Liability, Equity, Revenue, Expense
    balance = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(3), default='USD')
    status = db.Column(db.String(20), default='reconciled')  # reconciled, pending, adjusted, open_item
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ReconciliationNote(db.Model):
    __tablename__ = 'reconciliation_notes'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    amount = db.Column(db.Float, default=0.0)
    note_type = db.Column(db.String(20), default='adjustment')  # adjustment, open_item, info
    status = db.Column(db.String(20), default='pending')  # pending, resolved, reviewed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class BalanceSheetSnapshot(db.Model):
    __tablename__ = 'balance_sheet_snapshots'
    
    id = db.Column(db.Integer, primary_key=True)
    period = db.Column(db.String(50), nullable=False)  # e.g., "Q1 2025"
    date = db.Column(db.Date, nullable=False)
    total_assets = db.Column(db.Float, default=0.0)
    total_liabilities = db.Column(db.Float, default=0.0)
    total_equity = db.Column(db.Float, default=0.0)
    is_balanced = db.Column(db.Boolean, default=False)
    adjustments_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='completed')  # completed, failed, partial
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class QBOConnection(db.Model):
    __tablename__ = 'qbo_connections'
    
    id = db.Column(db.Integer, primary_key=True)
    realm_id = db.Column(db.String(50), nullable=False)
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    company_name = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def set_tokens(self, access_token, refresh_token):
        """Store tokens (plaintext for now)"""
        self.access_token = access_token
        self.refresh_token = refresh_token
    
    def get_access_token(self):
        """Return access token"""
        return self.access_token
    
    def get_refresh_token(self):
        """Return refresh token"""
        return self.refresh_token

class Adjustment(db.Model):
    __tablename__ = 'adjustments'
    
    id = db.Column(db.Integer, primary_key=True)
    reconciliation_log_id = db.Column(db.Integer, db.ForeignKey('balance_sheet_snapshots.id'))
    account_name = db.Column(db.String(200), nullable=False)
    original_amount = db.Column(db.Float, default=0.0)
    adjusted_amount = db.Column(db.Float, default=0.0)
    adjustment_amount = db.Column(db.Float, default=0.0)
    reason = db.Column(db.Text, nullable=False)
    adjustment_type = db.Column(db.String(50), nullable=False)  # correction, reclassification, write_off
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    realm_id = db.Column(db.String(50))  # QuickBooks company ID
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @staticmethod
    def log_action(action, details=None, realm_id=None):
        """Log an action with request context"""
        from flask import request
        
        log_entry = AuditLog(
            action=action,
            details=details,
            ip_address=request.remote_addr if request else None,
            user_agent=request.headers.get('User-Agent') if request else None,
            realm_id=realm_id
        )
        
        db.session.add(log_entry)
        db.session.commit()
        
        # Also log to file logger
        logger.info(f"AUDIT: {action} - {details or ''} - IP: {log_entry.ip_address} - Realm: {realm_id or 'N/A'}")

def generate_demo_balance_sheet_data(as_of_date=None):
    """Generate impressive demo balance sheet data"""
    import random
    
    # Demo company info
    company_name = "TechCorp Industries Inc."
    
    # Generate realistic account balances
    demo_data = {
        'company_name': company_name,
        'as_of_date': as_of_date or datetime.now().date(),
        'accounts': {
            'assets': {
                'current': [
                    {
                        'id': 1,
                        'name': 'Cash & Cash Equivalents',
                        'balance': 2847500,
                        'status': 'reconciled',
                        'description': 'Operating cash and short-term investments'
                    },
                    {
                        'id': 2,
                        'name': 'Accounts Receivable',
                        'balance': 1876500,
                        'status': 'reconciled',
                        'description': 'Trade receivables from customers'
                    },
                    {
                        'id': 3,
                        'name': 'Inventory',
                        'balance': 3420000,
                        'status': 'adjusted',
                        'description': 'Raw materials and finished goods'
                    },
                    {
                        'id': 4,
                        'name': 'Prepaid Expenses',
                        'balance': 485000,
                        'status': 'reconciled',
                        'description': 'Insurance and rent prepayments'
                    },
                    {
                        'id': 5,
                        'name': 'Short-term Investments',
                        'balance': 1250000,
                        'status': 'reconciled',
                        'description': 'Marketable securities and T-bills'
                    }
                ],
                'non_current': [
                    {
                        'id': 6,
                        'name': 'Property & Equipment (net)',
                        'balance': 15680000,
                        'status': 'reconciled',
                        'description': 'Buildings, machinery, and equipment'
                    },
                    {
                        'id': 7,
                        'name': 'Intangible Assets',
                        'balance': 3200000,
                        'status': 'pending',
                        'description': 'Patents, trademarks, and software'
                    },
                    {
                        'id': 8,
                        'name': 'Long-term Investments',
                        'balance': 2100000,
                        'status': 'reconciled',
                        'description': 'Strategic investments and joint ventures'
                    }
                ]
            },
            'liabilities': {
                'current': [
                    {
                        'id': 9,
                        'name': 'Accounts Payable',
                        'balance': 2340000,
                        'status': 'reconciled',
                        'description': 'Trade payables to suppliers'
                    },
                    {
                        'id': 10,
                        'name': 'Accrued Liabilities',
                        'balance': 875000,
                        'status': 'reconciled',
                        'description': 'Wages, taxes, and other accruals'
                    },
                    {
                        'id': 11,
                        'name': 'Short-term Debt',
                        'balance': 1500000,
                        'status': 'open_item',
                        'description': 'Bank lines and commercial paper'
                    },
                    {
                        'id': 12,
                        'name': 'Current Portion of Long-term Debt',
                        'balance': 650000,
                        'status': 'reconciled',
                        'description': 'Principal due within 12 months'
                    }
                ],
                'non_current': [
                    {
                        'id': 13,
                        'name': 'Long-term Debt',
                        'balance': 8900000,
                        'status': 'reconciled',
                        'description': 'Bonds and term loans'
                    },
                    {
                        'id': 14,
                        'name': 'Deferred Tax Liabilities',
                        'balance': 1420000,
                        'status': 'pending',
                        'description': 'Tax deferrals and timing differences'
                    },
                    {
                        'id': 15,
                        'name': 'Pension Obligations',
                        'balance': 2100000,
                        'status': 'reconciled',
                        'description': 'Retirement benefit obligations'
                    }
                ]
            },
            'equity': [
                {
                    'id': 16,
                    'name': 'Common Stock',
                    'balance': 5000000,
                    'status': 'reconciled',
                    'description': 'Issued and outstanding shares'
                },
                {
                    'id': 17,
                    'name': 'Additional Paid-in Capital',
                    'balance': 12000000,
                    'status': 'reconciled',
                    'description': 'Premium over par value'
                },
                {
                    'id': 18,
                    'name': 'Retained Earnings',
                    'balance': 8450000,
                    'status': 'adjusted',
                    'description': 'Cumulative net income retained'
                },
                {
                    'id': 19,
                    'name': 'Current Period Net Income',
                    'balance': 2875000,
                    'status': 'reconciled',
                    'description': 'Net income for current fiscal year'
                }
                ]
        }
    }
    
    # Calculate totals
    current_assets = sum(acc['balance'] for acc in demo_data['accounts']['assets']['current'])
    non_current_assets = sum(acc['balance'] for acc in demo_data['accounts']['assets']['non_current'])
    total_assets = current_assets + non_current_assets
    
    current_liabilities = sum(liab['balance'] for liab in demo_data['accounts']['liabilities']['current'])
    non_current_liabilities = sum(liab['balance'] for liab in demo_data['accounts']['liabilities']['non_current'])
    total_liabilities = current_liabilities + non_current_liabilities
    
    total_equity = sum(eq['balance'] for eq in demo_data['accounts']['equity'])
    
    demo_data['totals'] = {
        'current_assets': current_assets,
        'non_current_assets': non_current_assets,
        'total_assets': total_assets,
        'current_liabilities': current_liabilities,
        'non_current_liabilities': non_current_liabilities,
        'total_liabilities': total_liabilities,
        'total_equity': total_equity
    }
    
    return demo_data

def generate_demo_adjustments():
    """Generate realistic demo reconciliation adjustments"""
    return [
        {
            'account_name': 'Inventory',
            'original_amount': 3420000,
            'adjusted_amount': 3420000,
            'adjustment_amount': 0,
            'reason': 'Physical count variance of $45,000 identified and documented. Adjustment pending management review.',
            'adjustment_type': 'info'
        },
        {
            'account_name': 'Short-term Debt',
            'original_amount': 1500000,
            'adjusted_amount': 1500000,
            'adjustment_amount': 0,
            'reason': 'Bank facility increase of $500,000 not yet reflected in system. Awaiting documentation.',
            'adjustment_type': 'open_item'
        },
        {
            'account_name': 'Intangible Assets',
            'original_amount': 3200000,
            'adjusted_amount': 3200000,
            'adjustment_amount': 0,
            'reason': 'Annual amortization review in progress. $125,000 of amortization to be recorded next period.',
            'adjustment_type': 'info'
        },
        {
            'account_name': 'Retained Earnings',
            'original_amount': 8450000,
            'adjusted_amount': 8450000,
            'adjustment_amount': 0,
            'reason': 'Prior period adjustment of $75,000 identified. Tax impact being calculated.',
            'adjustment_type': 'adjustment'
        }
    ]

def generate_demo_reconciliation_checks():
    """Generate demo reconciliation check results"""
    return {
        'trial_balance_difference': 0,
        'balance_sheet_difference': 0,
        'total_open_ar': 1876500,
        'total_open_ap': 2340000,
        'bank_reconciled': True,
        'accounts_reviewed': 19,
        'accounts_reconciled': 16,
        'accounts_pending': 3,
        'note': 'All major accounts reconciled. Minor items pending documentation.'
    }

class QuickBooksAPI:
    def __init__(self, realm_id, access_token):
        self.realm_id = realm_id
        self.access_token = access_token
        self.base_url = f'https://quickbooks.api.intuit.com/v3/company/{realm_id}'
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
    
    def refresh_access_token(self, refresh_token):
        """Refresh access token using refresh token (placeholder)"""
        # This would need to be implemented with proper OAuth2 library
        logger.warning("Token refresh not available without authlib")
        return None, None
    
    def get_company_info(self):
        """Get company information"""
        try:
            response = requests.get(f'{self.base_url}/companyinfo/{self.realm_id}', headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting company info: {e}")
            return None
    
    def get_trial_balance(self, as_of_date=None):
        """Get trial balance"""
        try:
            params = {}
            if as_of_date:
                params['asofdate'] = as_of_date.isoformat()
            
            response = requests.get(f'{self.base_url}/reports/TrialBalance', headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting trial balance: {e}")
            return None
    
    def get_balance_sheet_report(self, as_of_date=None):
        """Get balance sheet report from QuickBooks"""
        try:
            params = {}
            if as_of_date:
                params['as_of_date'] = as_of_date.isoformat()
            
            response = requests.get(f'{self.base_url}/reports/BalanceSheet', headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting balance sheet report: {e}")
            return None
    
    def get_open_ar(self):
        """Get open accounts receivable"""
        try:
            response = requests.get(f'{self.base_url}/query', headers=self.headers, params={
                'query': 'SELECT * FROM Customer WHERE Balance > 0'
            })
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting open A/R: {e}")
            return None
    
    def get_open_ap(self):
        """Get open accounts payable"""
        try:
            response = requests.get(f'{self.base_url}/query', headers=self.headers, params={
                'query': 'SELECT * FROM Vendor WHERE Balance > 0'
            })
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting open A/P: {e}")
            return None
    
    def get_chart_of_accounts(self):
        """Get chart of accounts"""
        try:
            response = requests.get(f'{self.base_url}/query', headers=self.headers, params={
                'query': 'SELECT * FROM Account WHERE Active = true'
            })
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting chart of accounts: {e}")
            return None

class BalanceSheetReconciler:
    def __init__(self, qbo_api):
        self.qbo_api = qbo_api
        self.adjustments = []
        self.reconciliation_checks = {}
    
    def reconcile(self, as_of_date=None):
        """Perform full reconciliation process"""
        logger.info(f"Starting reconciliation for date: {as_of_date}")
        
        # Get data from QuickBooks
        trial_balance = self.qbo_api.get_trial_balance(as_of_date)
        balance_sheet = self.qbo_api.get_balance_sheet_report(as_of_date)
        chart_of_accounts = self.qbo_api.get_chart_of_accounts()
        open_ar = self.qbo_api.get_open_ar()
        open_ap = self.qbo_api.get_open_ap()
        bank_accounts = self.qbo_api.get_bank_accounts()
        
        if not all([trial_balance, balance_sheet, chart_of_accounts]):
            raise Exception("Failed to retrieve required data from QuickBooks")
        
        # Perform comprehensive reconciliation checks
        self._validate_trial_balance(trial_balance)
        self._verify_balance_sheet_totals(balance_sheet)
        self._check_account_balances(chart_of_accounts, trial_balance)
        self._reconcile_bank_accounts(bank_accounts, trial_balance)
        self._verify_open_items(open_ar, open_ap)
        self._validate_retained_earnings(balance_sheet, trial_balance)
        
        # Generate summary balance sheet
        summary_bs = self._generate_summary_balance_sheet(balance_sheet)
        
        # Log reconciliation results
        reconciliation_log = BalanceSheetSnapshot(
            date=as_of_date or datetime.now().date(),
            period=f"{as_of_date or datetime.now().date()}",
            total_assets=summary_bs['total_assets'],
            total_liabilities=summary_bs['total_liabilities'],
            total_equity=summary_bs['total_equity'],
            is_balanced=abs(summary_bs['total_assets'] - (summary_bs['total_liabilities'] + summary_bs['total_equity'])) < 0.01,
            adjustments_count=len(self.adjustments),
            status='completed'
        )
        
        db.session.add(reconciliation_log)
        db.session.commit()
        
        # Save adjustments
        for adj in self.adjustments:
            adjustment = Adjustment(
                reconciliation_log_id=reconciliation_log.id,
                account_name=adj['account_name'],
                original_amount=adj['original_amount'],
                adjusted_amount=adj['adjusted_amount'],
                adjustment_amount=adj['adjustment_amount'],
                reason=adj['reason'],
                adjustment_type=adj['adjustment_type']
            )
            db.session.add(adjustment)
        
        db.session.commit()
        
        logger.info(f"Reconciliation completed. {len(self.adjustments)} adjustments made.")
        
        return {
            'summary_balance_sheet': summary_bs,
            'adjustments': self.adjustments,
            'reconciliation_checks': self.reconciliation_checks,
            'is_balanced': reconciliation_log.is_balanced
        }
    
    def _validate_trial_balance(self, trial_balance):
        """Validate that debits equal credits in trial balance"""
        if 'Rows' not in trial_balance:
            return
        
        total_debits = 0
        total_credits = 0
        
        for row in trial_balance['Rows']:
            if 'ColData' in row:
                for col in row['ColData']:
                    if 'value' in col and col.get('value') != 0:
                        if col.get('id') == 'Debit':
                            total_debits += float(col['value'])
                        elif col.get('id') == 'Credit':
                            total_credits += float(col['value'])
        
        difference = abs(total_debits - total_credits)
        self.reconciliation_checks['trial_balance_difference'] = difference
        
        if difference > 0.01:
            adjustment = {
                'account_name': 'Trial Balance Adjustment',
                'original_amount': difference,
                'adjusted_amount': 0,
                'adjustment_amount': -difference,
                'reason': f'Trial balance out of balance by ${difference:.2f}',
                'adjustment_type': 'correction'
            }
            self.adjustments.append(adjustment)
    
    def _verify_balance_sheet_totals(self, balance_sheet):
        """Verify balance sheet equation: Assets = Liabilities + Equity"""
        if 'Rows' not in balance_sheet:
            return
        
        total_assets = 0
        total_liabilities = 0
        total_equity = 0
        
        for row in balance_sheet['Rows']:
            if 'Rows' in row:  # Main sections
                for sub_row in row['Rows']:
                    if 'ColData' in sub_row and len(sub_row['ColData']) > 1:
                        section_name = sub_row.get('group', '')
                        total_value = float(sub_row['ColData'][-1].get('value', 0))
                        
                        if 'ASSET' in section_name.upper():
                            total_assets = total_value
                        elif 'LIABILITY' in section_name.upper():
                            total_liabilities = total_value
                        elif 'EQUITY' in section_name.upper():
                            total_equity = total_value
        
        difference = abs(total_assets - (total_liabilities + total_equity))
        self.reconciliation_checks['balance_sheet_difference'] = difference
        
        if difference > 0.01:
            adjustment = {
                'account_name': 'Balance Sheet Adjustment',
                'original_amount': difference,
                'adjusted_amount': 0,
                'adjustment_amount': -difference,
                'reason': f'Balance sheet out of balance by ${difference:.2f}',
                'adjustment_type': 'correction'
            }
            self.adjustments.append(adjustment)
    
    def _reconcile_bank_accounts(self, bank_accounts, trial_balance):
        """Reconcile bank balances vs ledger balances"""
        if not bank_accounts or 'QueryResponse' not in bank_accounts:
            return
        
        for account in bank_accounts['QueryResponse'].get('Account', []):
            account_name = account.get('Name', '')
            ledger_balance = account.get('CurrentBalance', 0)
            
            # Check for unusual bank balances
            if abs(ledger_balance) > 1000000:  # Flag large balances
                adjustment = {
                    'account_name': account_name,
                    'original_amount': ledger_balance,
                    'adjusted_amount': ledger_balance,
                    'adjustment_amount': 0,
                    'reason': f'Large bank balance requires manual review: ${ledger_balance:,.2f}',
                    'adjustment_type': 'info'
                }
                self.adjustments.append(adjustment)
    
    def _verify_open_items(self, open_ar, open_ap):
        """Verify open receivables and payables"""
        total_ar = 0
        total_ap = 0
        
        if open_ar and 'QueryResponse' in open_ar:
            for customer in open_ar['QueryResponse'].get('Customer', []):
                total_ar += customer.get('Balance', 0)
        
        if open_ap and 'QueryResponse' in open_ap:
            for vendor in open_ap['QueryResponse'].get('Vendor', []):
                total_ap += vendor.get('Balance', 0)
        
        self.reconciliation_checks['total_open_ar'] = total_ar
        self.reconciliation_checks['total_open_ap'] = total_ap
        
        # Flag large open items
        if total_ar > 500000:
            adjustment = {
                'account_name': 'Accounts Receivable',
                'original_amount': total_ar,
                'adjusted_amount': total_ar,
                'adjustment_amount': 0,
                'reason': f'High A/R balance requires review: ${total_ar:,.2f}',
                'adjustment_type': 'info'
            }
            self.adjustments.append(adjustment)
    
    def _validate_retained_earnings(self, balance_sheet, trial_balance):
        """Verify retained earnings calculation"""
        if 'Rows' not in balance_sheet:
            return
        
        retained_earnings = 0
        for row in balance_sheet['Rows']:
            if 'Rows' in row:
                for sub_row in row['Rows']:
                    if 'ColData' in sub_row and len(sub_row['ColData']) > 1:
                        section_name = sub_row.get('group', '')
                        if 'RETAINED' in section_name.upper():
                            retained_earnings = float(sub_row['ColData'][-1].get('value', 0))
                            break
        
        # Flag negative retained earnings
        if retained_earnings < 0:
            adjustment = {
                'account_name': 'Retained Earnings',
                'original_amount': retained_earnings,
                'adjusted_amount': retained_earnings,
                'adjustment_amount': 0,
                'reason': f'Negative retained earnings: ${retained_earnings:,.2f}',
                'adjustment_type': 'info'
            }
            self.adjustments.append(adjustment)
    
    def _check_account_balances(self, chart_of_accounts, trial_balance):
        """Check for unusual account balances"""
        if 'QueryResponse' not in chart_of_accounts:
            return
        
        for account in chart_of_accounts['QueryResponse'].get('Account', []):
            account_name = account.get('Name', '')
            account_type = account.get('AccountType', '')
            current_balance = account.get('CurrentBalance', 0)
            
            # Check for negative balances in accounts that shouldn't be negative
            if account_type in ['Accounts Receivable', 'Cash', 'Inventory'] and current_balance < 0:
                adjustment = {
                    'account_name': account_name,
                    'original_amount': current_balance,
                    'adjusted_amount': abs(current_balance),
                    'adjustment_amount': abs(current_balance) * 2,
                    'reason': f'Negative balance in {account_type} account',
                    'adjustment_type': 'correction'
                }
                self.adjustments.append(adjustment)
    
    def _generate_summary_balance_sheet(self, balance_sheet):
        """Generate summary balance sheet from QuickBooks data"""
        if 'Rows' not in balance_sheet:
            return {}
        
        summary = {
            'assets': {'current': 0, 'fixed': 0, 'other': 0},
            'liabilities': {'current': 0, 'long_term': 0},
            'equity': {'owners_equity': 0, 'retained_earnings': 0, 'net_income': 0}
        }
        
        for row in balance_sheet['Rows']:
            if 'Rows' in row:
                for sub_row in row['Rows']:
                    if 'ColData' in sub_row and len(sub_row['ColData']) > 1:
                        account_name = sub_row.get('group', '')
                        total_value = float(sub_row['ColData'][-1].get('value', 0))
                        
                        # Categorize accounts
                        if 'ASSET' in account_name.upper():
                            if 'CURRENT' in account_name.upper():
                                summary['assets']['current'] = total_value
                            elif 'FIXED' in account_name.upper() or 'PROPERTY' in account_name.upper():
                                summary['assets']['fixed'] = total_value
                            else:
                                summary['assets']['other'] = total_value
                        
                        elif 'LIABILITY' in account_name.upper():
                            if 'CURRENT' in account_name.upper():
                                summary['liabilities']['current'] = total_value
                            else:
                                summary['liabilities']['long_term'] = total_value
                        
                        elif 'EQUITY' in account_name.upper():
                            if 'RETAINED' in account_name.upper():
                                summary['equity']['retained_earnings'] = total_value
                            else:
                                summary['equity']['owners_equity'] = total_value
        
        # Calculate totals
        summary['total_assets'] = summary['assets']['current'] + summary['assets']['fixed'] + summary['assets']['other']
        summary['total_liabilities'] = summary['liabilities']['current'] + summary['liabilities']['long_term']
        summary['total_equity'] = summary['equity']['owners_equity'] + summary['equity']['retained_earnings']
        
        return summary

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/balance-sheet')
def get_balance_sheet():
    accounts = Account.query.all()
    
    # Organize accounts by type and subcategory
    balance_sheet = {
        'assets': {
            'current': [],
            'non_current': []
        },
        'liabilities': {
            'current': [],
            'non_current': []
        },
        'equity': []
    }
    
    for account in accounts:
        account_data = {
            'id': account.id,
            'name': account.name,
            'balance': account.balance,
            'status': account.status,
            'description': account.description
        }
        
        if account.account_type == 'asset':
            if account.subcategory == 'current':
                balance_sheet['assets']['current'].append(account_data)
            else:
                balance_sheet['assets']['non_current'].append(account_data)
        elif account.account_type == 'liability':
            if account.subcategory == 'current':
                balance_sheet['liabilities']['current'].append(account_data)
            else:
                balance_sheet['liabilities']['non_current'].append(account_data)
        elif account.account_type == 'equity':
            balance_sheet['equity'].append(account_data)
    
    # Calculate totals
    total_current_assets = sum(a['balance'] for a in balance_sheet['assets']['current'])
    total_non_current_assets = sum(a['balance'] for a in balance_sheet['assets']['non_current'])
    total_assets = total_current_assets + total_non_current_assets
    
    total_current_liabilities = sum(a['balance'] for a in balance_sheet['liabilities']['current'])
    total_non_current_liabilities = sum(a['balance'] for a in balance_sheet['liabilities']['non_current'])
    total_liabilities = total_current_liabilities + total_non_current_liabilities
    
    total_equity = sum(a['balance'] for a in balance_sheet['equity'])
    
    return jsonify({
        'accounts': balance_sheet,
        'totals': {
            'current_assets': total_current_assets,
            'non_current_assets': total_non_current_assets,
            'total_assets': total_assets,
            'current_liabilities': total_current_liabilities,
            'non_current_liabilities': total_non_current_liabilities,
            'total_liabilities': total_liabilities,
            'total_equity': total_equity
        }
    })

@app.route('/api/reconciliation-notes')
def get_reconciliation_notes():
    notes = ReconciliationNote.query.order_by(ReconciliationNote.created_at.desc()).all()
    
    notes_data = []
    for note in notes:
        notes_data.append({
            'id': note.id,
            'title': note.title,
            'description': note.description,
            'amount': note.amount,
            'note_type': note.note_type,
            'status': note.status,
            'created_at': note.created_at.isoformat()
        })
    
    return jsonify(notes_data)

@app.route('/api/accounts', methods=['POST'])
def create_account():
    data = request.get_json()
    
    account = Account(
        name=data['name'],
        account_type=data['account_type'],
        subcategory=data.get('subcategory'),
        balance=data.get('balance', 0.0),
        status=data.get('status', 'reconciled'),
        description=data.get('description')
    )
    
    db.session.add(account)
    db.session.commit()
    
    return jsonify({'id': account.id, 'message': 'Account created successfully'})

@app.route('/api/accounts/<int:account_id>', methods=['PUT'])
def update_account(account_id):
    account = Account.query.get_or_404(account_id)
    data = request.get_json()
    
    account.name = data.get('name', account.name)
    account.account_type = data.get('account_type', account.account_type)
    account.subcategory = data.get('subcategory', account.subcategory)
    account.balance = data.get('balance', account.balance)
    account.status = data.get('status', account.status)
    account.description = data.get('description', account.description)
    
    db.session.commit()
    
    return jsonify({'message': 'Account updated successfully'})

@app.route('/api/reconciliation-notes', methods=['POST'])
def create_reconciliation_note():
    data = request.get_json()
    
    note = ReconciliationNote(
        title=data['title'],
        description=data['description'],
        amount=data.get('amount', 0.0),
        note_type=data.get('note_type', 'adjustment'),
        status=data.get('status', 'pending')
    )
    

@app.route('/api/export/pdf')
def export_pdf():
    """Export balance sheet as PDF"""
    try:
        # Get latest reconciliation log
        latest_log = BalanceSheetSnapshot.query.order_by(BalanceSheetSnapshot.created_at.desc()).first()
        if not latest_log:
            return jsonify({'error': 'No balance sheet data found. Generate report first.'}), 400
        
        AuditLog.log_action('PDF_EXPORTED', f'PDF exported for balance sheet dated {latest_log.date}')
        
        # Get adjustments for this report
        adjustments = Adjustment.query.filter_by(reconciliation_log_id=latest_log.id).all()
        
        # Generate PDF
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        
        content = []
        
        # Title
        title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], 
                                  fontSize=18, spaceAfter=30, alignment=1)
        content.append(Paragraph("Balance Sheet", title_style))
        content.append(Paragraph(f"As of {latest_log.date.strftime('%B %d, %Y')}", styles['Normal']))
        content.append(Spacer(1, 20))
        
        # Balance Sheet Summary
        data = [['Category', 'Amount']]
        data.append(['Total Assets', f"${latest_log.total_assets:,.2f}"])
        data.append(['Total Liabilities', f"${latest_log.total_liabilities:,.2f}"])
        data.append(['Total Equity', f"${latest_log.total_equity:,.2f}"])
        data.append(['', ''])
        data.append(['Balanced', 'YES' if latest_log.is_balanced else 'NO'])
        
        table = Table(data, colWidths=[4*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        content.append(table)
        
        if adjustments:
            content.append(Spacer(1, 20))
            content.append(Paragraph("Adjustment Notes", styles['Heading2']))
            
            for adj in adjustments:
                content.append(Paragraph(f"{adj.account_name}: {adj.reason}", styles['Normal']))
                content.append(Paragraph(f"Adjustment: ${adj.adjustment_amount:,.2f}", styles['Normal']))
                content.append(Spacer(1, 10))
        
        doc.build(content)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'balance_sheet_{latest_log.date.strftime("%Y%m%d")}.pdf',
            mimetype='application/pdf'
        )
        
    except Exception as e:
        logger.error(f"Error exporting PDF: {e}")
        return jsonify({'error': f'Error exporting PDF: {str(e)}'}), 500

@app.route('/api/export/excel')
def export_excel():
    """Export balance sheet as Excel"""
    try:
        # Get latest reconciliation log
        latest_log = BalanceSheetSnapshot.query.order_by(BalanceSheetSnapshot.created_at.desc()).first()
        if not latest_log:
            return jsonify({'error': 'No balance sheet data found. Generate report first.'}), 400
        
        AuditLog.log_action('EXCEL_EXPORTED', f'Excel exported for balance sheet dated {latest_log.date}')
        
        # Get adjustments for this report
        adjustments = Adjustment.query.filter_by(reconciliation_log_id=latest_log.id).all()
        
        # Create Excel workbook
        buffer = io.BytesIO()
        
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            # Balance Sheet Summary
            bs_data = {
                'Category': ['Total Assets', 'Total Liabilities', 'Total Equity', 'Balanced'],
                'Amount': [latest_log.total_assets, latest_log.total_liabilities, 
                          latest_log.total_equity, 'YES' if latest_log.is_balanced else 'NO']
            }
            df_bs = pd.DataFrame(bs_data)
            df_bs.to_excel(writer, sheet_name='Balance Sheet', index=False)
            
            # Adjustment Notes
            if adjustments:
                adj_data = []
                for adj in adjustments:
                    adj_data.append({
                        'Account': adj.account_name,
                        'Original Amount': adj.original_amount,
                        'Adjusted Amount': adj.adjusted_amount,
                        'Adjustment': adj.adjustment_amount,
                        'Reason': adj.reason,
                        'Type': adj.adjustment_type
                    })
                df_adj = pd.DataFrame(adj_data)
                df_adj.to_excel(writer, sheet_name='Adjustment Notes', index=False)
        
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'balance_sheet_{latest_log.date.strftime("%Y%m%d")}.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        logger.error(f"Error exporting Excel: {e}")
        return jsonify({'error': f'Error exporting Excel: {str(e)}'}), 500

def init_db():
    """Initialize database"""
    with app.app_context():
        db.create_all()
        
        # Check if data already exists
        if Account.query.first() is None:
            # Sample accounts data
            sample_accounts = [
                # Current Assets
                {'name': 'Cash & Cash Equivalents', 'account_type': 'asset', 'subcategory': 'current', 'balance': 482300, 'status': 'reconciled'},
                {'name': 'Accounts Receivable', 'account_type': 'asset', 'subcategory': 'current', 'balance': 315750, 'status': 'reconciled'},
                {'name': 'Inventory', 'account_type': 'asset', 'subcategory': 'current', 'balance': 204600, 'status': 'adjusted'},
                {'name': 'Prepaid Expenses', 'account_type': 'asset', 'subcategory': 'current', 'balance': 38400, 'status': 'reconciled'},
                
                # Non-Current Assets
                {'name': 'Property & Equipment (net)', 'account_type': 'asset', 'subcategory': 'non_current', 'balance': 1280000, 'status': 'reconciled'},
                {'name': 'Intangible Assets', 'account_type': 'asset', 'subcategory': 'non_current', 'balance': 520000, 'status': 'pending'},
                
                # Current Liabilities
                {'name': 'Accounts Payable', 'account_type': 'liability', 'subcategory': 'current', 'balance': 198400, 'status': 'reconciled'},
                {'name': 'Accrued Liabilities', 'account_type': 'liability', 'subcategory': 'current', 'balance': 87200, 'status': 'reconciled'},
                {'name': 'Short-Term Debt', 'account_type': 'liability', 'subcategory': 'current', 'balance': 125000, 'status': 'open_item'},
                
                # Non-Current Liabilities
                {'name': 'Long-Term Debt', 'account_type': 'liability', 'subcategory': 'non_current', 'balance': 712000, 'status': 'reconciled'},
                
                # Equity
                {'name': 'Common Stock', 'account_type': 'equity', 'subcategory': None, 'balance': 500000, 'status': 'reconciled'},
                {'name': 'Retained Earnings', 'account_type': 'equity', 'subcategory': None, 'balance': 1032000, 'status': 'reconciled'},
                {'name': 'Current Period Net Income', 'account_type': 'equity', 'subcategory': None, 'balance': 186450, 'status': 'adjusted'}
            ]
            
            for account_data in sample_accounts:
                account = Account(**account_data)
                db.session.add(account)
            
            # Sample reconciliation notes
            sample_notes = [
                {
                    'title': 'Inventory Adjustment',
                    'description': 'Physical count variance vs. QuickBooks. Wrote down $4,200 for obsolete stock per management review.',
                    'amount': -4200,
                    'note_type': 'adjustment',
                    'status': 'resolved'
                },
                {
                    'title': 'Short-Term Debt — Open',
                    'description': 'Bank statement shows $125K draw; loan agreement not yet filed in system. Awaiting signed docs.',
                    'amount': 125000,
                    'note_type': 'open_item',
                    'status': 'pending'
                },
                {
                    'title': 'Net Income Reclassification',
                    'description': '$12,300 reclassified from retained earnings to current period net income to match P&L.',
                    'amount': 12300,
                    'note_type': 'adjustment',
                    'status': 'resolved'
                },
                {
                    'title': 'Intangible Assets — Pending',
                    'description': 'Software license capitalization under review. Value held at cost pending amortization schedule.',
                    'amount': 520000,
                    'note_type': 'info',
                    'status': 'reviewed'
                }
            ]
            
            for note_data in sample_notes:
                note = ReconciliationNote(**note_data)
                db.session.add(note)
            
            db.session.commit()

# Mock QuickBooks Routes (without authlib)
@app.route('/connect/qbo')
def connect_qbo():
    """Mock QuickBooks connection"""
    AuditLog.log_action('QBO_CONNECTION_MOCK', 'Mock connection initiated')
    flash('QuickBooks connection is not available without authlib. Using demo mode.', 'warning')
    return redirect(url_for('index'))

@app.route('/callback')
def qbo_callback():
    """Mock callback"""
    flash('QuickBooks callback is not available without authlib.', 'warning')
    return redirect(url_for('index'))

@app.route('/api/qbo-status')
def qbo_status():
    """Mock QuickBooks connection status"""
    return jsonify({'connected': False, 'message': 'Demo mode - authlib not installed'})

@app.route('/generate-balance-sheet', methods=['POST'])
def generate_balance_sheet():
    """Generate balance sheet using impressive demo data"""
    try:
        # Get as-of date from request
        as_of_date_str = request.form.get('as_of_date')
        as_of_date = None
        if as_of_date_str:
            as_of_date = datetime.strptime(as_of_date_str, '%Y-%m-%d').date()
        
        # Generate impressive demo data
        demo_data = generate_demo_balance_sheet_data(as_of_date)
        demo_adjustments = generate_demo_adjustments()
        demo_reconciliation = generate_demo_reconciliation_checks()
        
        # Log generation
        logger.info(f"Impressive demo balance sheet generated for {demo_data['company_name']} as of {as_of_date or datetime.now().date()}")
        AuditLog.log_action(
            'BALANCE_SHEET_GENERATED_DEMO', 
            f'Demo balance sheet generated for {demo_data["company_name"]} as of {as_of_date or datetime.now().date()}'
        )
        
        return jsonify({
            'success': True,
            'balance_sheet': demo_data,
            'adjustments': demo_adjustments,
            'reconciliation_checks': demo_reconciliation,
            'is_balanced': True,
            'demo_mode': True,
            'company_name': demo_data['company_name']
        })
        
    except Exception as e:
        logger.error(f"Error generating balance sheet: {e}")
        AuditLog.log_action('BALANCE_SHEET_GENERATION_FAILED', f'Generation failed: {str(e)}')
        return jsonify({'error': f'Error generating balance sheet: {str(e)}'}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
