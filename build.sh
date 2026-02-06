#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

# Initialize database tables
python -c "
from run import app
from app import db
from sqlalchemy import text

with app.app_context():
    # Create public schema tables (licenses)
    db.session.execute(text('SET search_path TO public'))
    db.session.commit()
    db.create_all()
    print('Database tables created in public schema')
"

