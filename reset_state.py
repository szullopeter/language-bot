import os
import sqlite3
from config import Config

def reset_state():
    db_path = Config.DB_PATH
    print(f"Starting reset for database: {db_path}")

    # 1. Close any existing connections if necessary (not needed for simple file delete)
    
    # 2. Delete the database file
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            print(f"Successfully deleted database file: {db_path}")
        except Exception as e:
            print(f"Error deleting database file: {e}")
    else:
        print(f"Database file does not exist: {db_path}")

    # 3. Optional: Clear logs if they are in a specific file
    # (Assuming logs are handled by standard logging, often directed to stdout or a file we'd need to find)
    
    # 4. Re-initialize the database by importing the Database class
    # This will trigger __init__ -> _init_db()
    try:
        from database import Database
        db = Database()
        print("Database re-initialized with fresh tables.")
    except Exception as e:
        print(f"Error re-initializing database: {e}")

    print("Reset complete. The application is back to a clean state.")

if __name__ == "__main__":
    confirm = input("Are you sure you want to reset EVERYTHING? This will delete all users, history, and vocabulary. (y/n): ")
    if confirm.lower() == 'y':
        reset_state()
    else:
        print("Reset cancelled.")
