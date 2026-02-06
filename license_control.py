"""
License Control Module for DED Control Panel
وحدة التحكم في التراخيص لـ DED Control Panel
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

class LicenseControl:
    """License Control Class"""
    
    def __init__(self, db_path=None):
        """Initialize with database path"""
        if db_path is None:
            self.db_path = Path(__file__).parent / 'licenses_master.db'
        else:
            self.db_path = Path(db_path)
    
    def get_connection(self):
        """Get database connection"""
        return sqlite3.connect(str(self.db_path))
    
    def get_all_licenses(self):
        """Get all licenses with full details"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT license_key, client_name, client_company, admin_username,
                   is_active, is_suspended, suspension_reason, expires_at, 
                   created_at, max_users, client_email, client_phone
            FROM licenses
            ORDER BY created_at DESC
        ''')
        
        licenses = []
        for row in cursor.fetchall():
            licenses.append({
                'license_key': row[0],
                'client_name': row[1],
                'client_company': row[2],
                'admin_username': row[3],
                'is_active': bool(row[4]),
                'is_suspended': bool(row[5]),
                'suspension_reason': row[6],
                'expires_at': row[7],
                'created_at': row[8],
                'max_users': row[9],
                'client_email': row[10],
                'client_phone': row[11]
            })
        
        conn.close()
        return licenses
    
    def activate_license(self, license_key):
        """Activate a license"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE licenses
                SET is_active = 1, is_suspended = 0, suspension_reason = NULL
                WHERE license_key = ?
            ''', (license_key,))
            
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            
            return affected > 0, "تم تفعيل الترخيص بنجاح" if affected > 0 else "الترخيص غير موجود"
        except Exception as e:
            return False, f"خطأ: {str(e)}"
    
    def suspend_license(self, license_key, reason="تم الإيقاف من لوحة التحكم"):
        """Suspend a license"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE licenses
                SET is_suspended = 1, suspension_reason = ?
                WHERE license_key = ?
            ''', (reason, license_key))
            
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            
            return affected > 0, "تم إيقاف الترخيص بنجاح" if affected > 0 else "الترخيص غير موجود"
        except Exception as e:
            return False, f"خطأ: {str(e)}"
    
    def deactivate_license(self, license_key):
        """Deactivate a license"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE licenses
                SET is_active = 0
                WHERE license_key = ?
            ''', (license_key,))
            
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            
            return affected > 0, "تم إلغاء تفعيل الترخيص بنجاح" if affected > 0 else "الترخيص غير موجود"
        except Exception as e:
            return False, f"خطأ: {str(e)}"
    
    def extend_license(self, license_key, days=30):
        """Extend license expiration"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Get current expiration
            cursor.execute('SELECT expires_at FROM licenses WHERE license_key = ?', (license_key,))
            row = cursor.fetchone()
            
            if not row:
                conn.close()
                return False, "الترخيص غير موجود"
            
            current_expires = row[0]
            
            # Parse current expiration
            if current_expires:
                try:
                    expires_dt = datetime.strptime(current_expires, '%Y-%m-%d %H:%M:%S')
                except:
                    try:
                        expires_dt = datetime.strptime(current_expires.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    except:
                        expires_dt = datetime.now()
            else:
                expires_dt = datetime.now()
            
            # Add days
            new_expires = expires_dt + timedelta(days=days)
            
            cursor.execute('''
                UPDATE licenses
                SET expires_at = ?
                WHERE license_key = ?
            ''', (new_expires.strftime('%Y-%m-%d %H:%M:%S'), license_key))
            
            conn.commit()
            conn.close()
            
            return True, f"تم تمديد الترخيص لمدة {days} يوم\nتاريخ الانتهاء الجديد: {new_expires.strftime('%Y-%m-%d')}"
        except Exception as e:
            return False, f"خطأ: {str(e)}"

