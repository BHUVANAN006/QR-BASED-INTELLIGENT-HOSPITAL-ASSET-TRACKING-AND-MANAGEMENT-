from pathlib import Path
import sqlite3
from werkzeug.security import generate_password_hash


def find_database():
    database_files = set()

    for pattern in ("*.db", "*.sqlite", "*.sqlite3"):
        for file_path in Path(".").rglob(pattern):
            if ".venv" not in file_path.parts:
                database_files.add(file_path)

    for database_path in database_files:
        try:
            connection = sqlite3.connect(database_path)

            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()

            table_names = {table[0] for table in tables}

            if "users" in table_names:
                columns = connection.execute(
                    "PRAGMA table_info(users)"
                ).fetchall()

                column_names = {column[1] for column in columns}

                if {"employee_id", "password_hash"}.issubset(column_names):
                    return database_path, connection

            connection.close()

        except sqlite3.Error:
            continue

    return None, None


database_path, connection = find_database()

if connection is None:
    print("MediTrack database was not found.")
    print("Upload your app.py file so the database location can be checked.")
    raise SystemExit(1)

print(f"\nDatabase found: {database_path}\n")

users = connection.execute(
    """
    SELECT employee_id, employee_name, role
    FROM users
    ORDER BY role, employee_id
    """
).fetchall()

if not users:
    print("No user accounts were found.")
    connection.close()
    raise SystemExit(1)

print("Available accounts:")
print("-" * 55)

for employee_id, employee_name, role in users:
    print(f"User ID: {employee_id} | Name: {employee_name} | Role: {role}")

print("-" * 55)

employee_id = input("\nEnter the User ID to reset: ").strip()

account = connection.execute(
    "SELECT employee_id FROM users WHERE employee_id = ?",
    (employee_id,),
).fetchone()

if account is None:
    print("That User ID was not found.")
    connection.close()
    raise SystemExit(1)

new_password = input("Enter a new password with at least 8 characters: ")

if len(new_password) < 8:
    print("Password must contain at least 8 characters.")
    connection.close()
    raise SystemExit(1)

confirm_password = input("Enter the new password again: ")

if new_password != confirm_password:
    print("The passwords do not match.")
    connection.close()
    raise SystemExit(1)

connection.execute(
    "UPDATE users SET password_hash = ? WHERE employee_id = ?",
    (generate_password_hash(new_password), employee_id),
)

connection.commit()
connection.close()

print("\nPassword reset successfully.")
print(f"User ID: {employee_id}")
print("You can now log in using the new password.")