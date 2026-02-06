"""
Multi-Tenancy Middleware
Middleware للتعامل مع قواعد البيانات المتعددة
Supports PostgreSQL schemas (production) and SQLite files (local dev)
"""
from flask import request, redirect, url_for, flash, session, g, current_app
from flask_login import current_user
from datetime import datetime
from sqlalchemy import text
from app.models_license import License
from app.tenant_manager import TenantManager, _is_postgres
from app import db

# Routes that don't require tenant database
EXEMPT_ROUTES = [
    '/static/',
    '/auth/login',
    '/auth/logout',
    '/auth/register',
    '/security/license',
    '/security/create_license',
    '/_debug_toolbar/',
    '/favicon.ico',
]


def init_tenant_middleware(app):
    """Initialize multi-tenancy middleware."""

    @app.before_request
    def switch_tenant_database():
        """Switch to appropriate tenant schema/database before each request."""

        # Skip for exempt routes
        for exempt_route in EXEMPT_ROUTES:
            if request.path.startswith(exempt_route):
                return None

        # Get current tenant from session
        tenant_license_key = session.get('tenant_license_key')

        if not tenant_license_key:
            if current_user.is_authenticated:
                flash('خطأ في تحديد الترخيص. يرجى تسجيل الدخول مرة أخرى.', 'error')
                return redirect(url_for('auth.logout'))
            return redirect(url_for('auth.login'))

        try:
            if _is_postgres(app):
                # ── PostgreSQL: query license in public schema ──
                db.session.execute(text("SET search_path TO public"))

                license = License.query.filter_by(
                    license_key=tenant_license_key,
                    is_active=True,
                    is_suspended=False
                ).first()
            else:
                # ── SQLite: switch to master DB to verify license ──
                master_db_uri = f'sqlite:///{TenantManager.get_master_db_path()}'
                app.config['SQLALCHEMY_DATABASE_URI'] = master_db_uri
                if hasattr(db, 'engine'):
                    db.engine.dispose()
                if hasattr(db, '_engine'):
                    db._engine = None

                license = License.query.filter_by(
                    license_key=tenant_license_key,
                    is_active=True,
                    is_suspended=False
                ).first()

            if not license:
                flash('الترخيص غير نشط أو معلق. يرجى الاتصال بالدعم.', 'error')
                session.pop('tenant_license_key', None)
                return redirect(url_for('auth.login'))

            if license.expires_at and license.expires_at < datetime.utcnow():
                flash('انتهت صلاحية الترخيص. يرجى تجديد الترخيص.', 'error')
                session.pop('tenant_license_key', None)
                return redirect(url_for('auth.login'))

            # Store license data as dict (avoid DetachedInstanceError)
            g.license_data = {
                'id': license.id,
                'license_key': license.license_key,
                'client_name': license.client_name,
                'client_email': license.client_email,
                'license_type': license.license_type,
                'expires_at': license.expires_at,
                'is_active': license.is_active,
                'is_suspended': license.is_suspended
            }
            g.tenant_license_key = tenant_license_key

        finally:
            # Now switch to the tenant schema/database
            if _is_postgres(app):
                TenantManager.switch_schema(db.session, tenant_license_key)
            else:
                tenant_db_uri = TenantManager.get_tenant_db_uri(tenant_license_key)
                app.config['SQLALCHEMY_DATABASE_URI'] = tenant_db_uri
                if hasattr(db, 'engine'):
                    db.engine.dispose()
                if hasattr(db, '_engine'):
                    db._engine = None

        return None

    @app.context_processor
    def inject_license():
        """Inject license information into all templates."""
        license_data = getattr(g, 'license_data', None)
        return dict(license=license_data)

