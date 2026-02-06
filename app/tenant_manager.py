"""
Multi-Tenancy Manager
مدير التعددية - كل ترخيص له PostgreSQL schema منفصل
Supports both PostgreSQL (production/Render) and SQLite (local development)
"""
import os
from flask import g, session
from sqlalchemy import text, inspect


def _is_postgres(app=None):
    """Check if we're using PostgreSQL"""
    if app:
        uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    else:
        uri = os.environ.get('DATABASE_URL', '')
    return 'postgresql' in uri or 'postgres' in uri


class TenantManager:
    """
    Manages multiple tenant databases/schemas.
    - PostgreSQL: one schema per license (tenant_XXXX_XXXX_XXXX_XXXX)
    - SQLite: one database file per license (fallback for local dev)
    """

    MASTER_DB = 'licenses_master.db'
    TENANTS_DIR = 'tenant_databases'

    # ── Helper: schema name from license key ──
    @staticmethod
    def _schema_name(license_key):
        return 'tenant_' + license_key.replace('-', '_').lower()

    # ── SQLite helpers (local dev only) ──
    @staticmethod
    def get_master_db_path():
        basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        return os.path.join(basedir, TenantManager.MASTER_DB)

    @staticmethod
    def get_tenants_dir():
        basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        tenants_path = os.path.join(basedir, TenantManager.TENANTS_DIR)
        if not os.path.exists(tenants_path):
            os.makedirs(tenants_path)
        return tenants_path

    @staticmethod
    def get_tenant_db_path(license_key):
        safe_key = license_key.replace('-', '_')
        return os.path.join(TenantManager.get_tenants_dir(), f"tenant_{safe_key}.db")

    @staticmethod
    def get_tenant_db_uri(license_key):
        """Return SQLite URI (local) or the main PostgreSQL URI (production)."""
        from flask import current_app
        if _is_postgres(current_app):
            return current_app.config['SQLALCHEMY_DATABASE_URI']
        return f'sqlite:///{TenantManager.get_tenant_db_path(license_key)}'

    # ── Schema switching (PostgreSQL) ──
    @staticmethod
    def switch_schema(db_session, license_key):
        """Set PostgreSQL search_path to tenant schema + public."""
        schema = TenantManager._schema_name(license_key)
        db_session.execute(text(f"SET search_path TO {schema}, public"))

    @staticmethod
    def switch_to_public(db_session):
        """Reset search_path to public schema only."""
        db_session.execute(text("SET search_path TO public"))

    # ── Create tenant ──
    @staticmethod
    def create_tenant_database(license_key, app):
        """Create tenant schema (PostgreSQL) or database file (SQLite)."""
        try:
            from app import db

            if _is_postgres(app):
                schema = TenantManager._schema_name(license_key)
                with app.app_context():
                    db.session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
                    db.session.execute(text(f"SET search_path TO {schema}, public"))
                    db.session.commit()

                    # Import all models
                    import app.models
                    import app.models_inventory
                    import app.models_sales
                    import app.models_purchases
                    import app.models_accounting
                    import app.models_crm
                    import app.models_hr
                    import app.models_pos
                    import app.models_settings

                    # Create tables in tenant schema
                    db.create_all()
                    db.session.execute(text("SET search_path TO public"))
                    db.session.commit()

                print(f"SUCCESS: Created PostgreSQL schema '{schema}'")
                return True
            else:
                # SQLite fallback
                from sqlalchemy import create_engine
                db_path = TenantManager.get_tenant_db_path(license_key)
                if os.path.exists(db_path):
                    return True
                engine = create_engine(f'sqlite:///{db_path}')
                import app.models, app.models_inventory, app.models_sales
                import app.models_purchases, app.models_accounting
                import app.models_crm, app.models_hr, app.models_pos
                import app.models_settings
                db.metadata.create_all(engine)
                engine.dispose()
                print(f"SUCCESS: Created SQLite tenant DB for {license_key}")
                return True

        except Exception as e:
            print(f"ERROR creating tenant for {license_key}: {e}")
            return False
    
    @staticmethod
    def initialize_tenant_data(license_key, app, license_obj):
        """Initialize tenant database/schema with default data."""
        try:
            from app import db
            from app.models import User, Role, Branch
            from app.models_accounting import Account

            if _is_postgres(app):
                # ── PostgreSQL: switch search_path then use db.session ──
                with app.app_context():
                    schema = TenantManager._schema_name(license_key)
                    db.session.execute(text(f"SET search_path TO {schema}, public"))

                    sess = db.session
            else:
                # ── SQLite: create a separate engine / session ──
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker, scoped_session
                engine = create_engine(TenantManager.get_tenant_db_uri(license_key))
                sess = scoped_session(sessionmaker(bind=engine))()

            # -- Roles --
            admin_role = sess.query(Role).filter_by(name='admin').first()
            if not admin_role:
                admin_role = Role(name='admin', name_ar='مدير النظام', description='Full system access')
                sess.add(admin_role)
            manager_role = sess.query(Role).filter_by(name='manager').first()
            if not manager_role:
                sess.add(Role(name='manager', name_ar='مدير', description='Manager access'))
            user_role = sess.query(Role).filter_by(name='user').first()
            if not user_role:
                sess.add(Role(name='user', name_ar='مستخدم', description='Basic user access'))
            sess.flush()

            # -- Branch --
            main_branch = sess.query(Branch).filter_by(code='MAIN').first()
            if not main_branch:
                main_branch = Branch(name='الفرع الرئيسي', name_en='Main Branch', code='MAIN', is_active=True)
                sess.add(main_branch)
                sess.flush()

            # -- Admin user --
            if license_obj.admin_username and license_obj.admin_password_hash:
                admin_user = sess.query(User).filter_by(username=license_obj.admin_username).first()
                email = license_obj.client_email
                if not email or '@' not in email:
                    email = f"{license_obj.admin_username}@{license_obj.client_company or 'company'}.com"
                existing_email = sess.query(User).filter_by(email=email).first()

                if not admin_user and not existing_email:
                    admin_user = User(
                        username=license_obj.admin_username,
                        email=email,
                        full_name=license_obj.client_name,
                        phone=license_obj.client_phone,
                        is_active=True, is_admin=True,
                        role_id=admin_role.id,
                        branch_id=main_branch.id
                    )
                    admin_user.password_hash = license_obj.admin_password_hash
                    sess.add(admin_user)

            # -- Chart of Accounts --
            for acc in [
                {'code': '1000', 'name': 'الأصول', 'name_en': 'Assets', 'account_type': 'asset'},
                {'code': '2000', 'name': 'الخصوم', 'name_en': 'Liabilities', 'account_type': 'liability'},
                {'code': '3000', 'name': 'حقوق الملكية', 'name_en': 'Equity', 'account_type': 'equity'},
                {'code': '4000', 'name': 'الإيرادات', 'name_en': 'Revenue', 'account_type': 'revenue'},
                {'code': '5000', 'name': 'المصروفات', 'name_en': 'Expenses', 'account_type': 'expense'},
            ]:
                if not sess.query(Account).filter_by(code=acc['code']).first():
                    sess.add(Account(code=acc['code'], name=acc['name'],
                                     name_en=acc['name_en'], account_type=acc['account_type'],
                                     is_system=True))

            sess.commit()

            if _is_postgres(app):
                db.session.execute(text("SET search_path TO public"))
                db.session.commit()
            else:
                sess.close()
                engine.dispose()

            print(f"SUCCESS: Initialized tenant data for {license_key}")
            return True

        except Exception as e:
            print(f"ERROR initializing tenant data for {license_key}: {e}")
            try:
                sess.rollback()
                if not _is_postgres(app):
                    sess.close()
                    engine.dispose()
                else:
                    db.session.execute(text("SET search_path TO public"))
            except:
                pass
            return False

    # ── Tenant context helpers ──
    @staticmethod
    def set_current_tenant(license_key):
        g.tenant_license_key = license_key
        session['tenant_license_key'] = license_key

    @staticmethod
    def get_current_tenant():
        if hasattr(g, 'tenant_license_key'):
            return g.tenant_license_key
        return session.get('tenant_license_key')

    @staticmethod
    def switch_tenant_database(app, license_key):
        """Switch to a specific tenant (schema or database file)."""
        try:
            from app import db
            if _is_postgres(app):
                TenantManager.switch_schema(db.session, license_key)
            else:
                db_path = TenantManager.get_tenant_db_path(license_key)
                if not os.path.exists(db_path):
                    print(f"Tenant DB not found for {license_key}")
                    return False
                app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

            TenantManager.set_current_tenant(license_key)
            return True
        except Exception as e:
            print(f"Error switching to tenant {license_key}: {e}")
            return False

    @staticmethod
    def delete_tenant_database(license_key):
        """Delete a tenant schema (PostgreSQL) or database file (SQLite)."""
        try:
            from flask import current_app
            if _is_postgres(current_app):
                from app import db
                schema = TenantManager._schema_name(license_key)
                db.session.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
                db.session.commit()
                print(f"Deleted PostgreSQL schema '{schema}'")
                return True
            else:
                db_path = TenantManager.get_tenant_db_path(license_key)
                if os.path.exists(db_path):
                    os.remove(db_path)
                    return True
                return False
        except Exception as e:
            print(f"Error deleting tenant for {license_key}: {e}")
            return False

    @staticmethod
    def list_all_tenants():
        """List all tenant license keys."""
        try:
            from flask import current_app
            if _is_postgres(current_app):
                from app import db
                result = db.session.execute(
                    text("SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'tenant_%'")
                )
                keys = []
                for row in result:
                    name = row[0].replace('tenant_', '').replace('_', '-').upper()
                    keys.append(name)
                return keys
            else:
                tenants_dir = TenantManager.get_tenants_dir()
                files = [f for f in os.listdir(tenants_dir) if f.startswith('tenant_') and f.endswith('.db')]
                return [f[7:-3].replace('_', '-') for f in files]
        except Exception as e:
            print(f"Error listing tenants: {e}")
            return []

