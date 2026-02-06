"""
Multi-Tenant Login Handler
معالج تسجيل الدخول للنظام متعدد التراخيص
Supports PostgreSQL schemas (production) and SQLite files (local dev)
"""
from flask import session, current_app
from datetime import datetime
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
from app import db
from app.models import User
from app.models_license import License
from app.tenant_manager import TenantManager, _is_postgres
import os


def authenticate_with_license(username, password, license_key, app):
    """
    Authenticate user with multi-tenancy support.
    Returns: (success: bool, message: str, user: User or None)
    """

    with app.app_context():
        # ─── Step 1: Verify license in master/public ───
        if _is_postgres(app):
            db.session.execute(text("SET search_path TO public"))
        else:
            master_uri = f'sqlite:///{TenantManager.get_master_db_path()}'
            app.config['SQLALCHEMY_DATABASE_URI'] = master_uri
            if hasattr(db, 'engine'):
                db.engine.dispose()
            if hasattr(db, '_engine'):
                db._engine = None

        lic = License.query.filter_by(license_key=license_key).first()
        if not lic:
            return False, '🔑 مفتاح الترخيص غير صحيح', None
        if not lic.is_active:
            return False, '🔑 الترخيص غير نشط', None
        if lic.is_suspended:
            return False, f'🔑 الترخيص معلق: {lic.suspension_reason or "يرجى الاتصال بالدعم"}', None
        if lic.expires_at and lic.expires_at < datetime.utcnow():
            return False, '🔑 انتهت صلاحية الترخيص', None

        # ─── Step 2: Ensure tenant schema/DB exists ───
        if _is_postgres(app):
            schema = TenantManager._schema_name(license_key)
            res = db.session.execute(
                text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = :s"),
                {'s': schema}
            )
            if not res.fetchone():
                if not TenantManager.create_tenant_database(license_key, app):
                    return False, '❌ فشل إنشاء قاعدة بيانات الترخيص', None
                if not TenantManager.initialize_tenant_data(license_key, app, lic):
                    return False, '❌ فشل تهيئة بيانات الترخيص', None
        else:
            tenant_db_path = TenantManager.get_tenant_db_path(license_key)
            if not os.path.exists(tenant_db_path):
                if not TenantManager.create_tenant_database(license_key, app):
                    return False, '❌ فشل إنشاء قاعدة بيانات الترخيص', None
                if not TenantManager.initialize_tenant_data(license_key, app, lic):
                    return False, '❌ فشل تهيئة بيانات الترخيص', None

        # ─── Step 3: Authenticate user in tenant schema/DB ───
        if _is_postgres(app):
            TenantManager.switch_schema(db.session, license_key)
            user = User.query.filter_by(username=username).first()
        else:
            tenant_engine = create_engine(f'sqlite:///{TenantManager.get_tenant_db_path(license_key)}')
            TenantSession = sessionmaker(bind=tenant_engine)
            tsess = TenantSession()
            try:
                user = tsess.query(User).filter_by(username=username).first()
            finally:
                tsess.close()
                tenant_engine.dispose()

        if not user:
            return False, '❌ اسم المستخدم غير موجود', None
        if not user.check_password(password):
            return False, '❌ كلمة المرور غير صحيحة', None
        if not user.is_active:
            return False, '❌ الحساب غير نشط', None

        # ─── Step 4: Switch to tenant DB/schema for the rest of the request ───
        user_id = user.id

        if _is_postgres(app):
            # Already in tenant schema - just update last_login
            user.last_login = datetime.utcnow()
            db.session.commit()
            # Reload user from current session
            user = db.session.get(User, user_id)
        else:
            # Switch Flask-SQLAlchemy to tenant database
            tenant_db_uri = TenantManager.get_tenant_db_uri(license_key)
            app.config['SQLALCHEMY_DATABASE_URI'] = tenant_db_uri
            if hasattr(db, 'engine'):
                db.engine.dispose()
            if hasattr(db, '_engine'):
                db._engine = None

            # Reload user via Flask-SQLAlchemy on the tenant DB
            user = db.session.get(User, user_id)
            if user:
                user.last_login = datetime.utcnow()
                db.session.commit()

        if not user:
            return False, '❌ خطأ في تحميل بيانات المستخدم', None

        try:
            session['tenant_license_key'] = license_key
        except RuntimeError:
            pass

        return True, '✅ تم تسجيل الدخول بنجاح', user

