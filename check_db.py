#!/usr/bin/env python3
import sqlite3
import os

# Check if database exists
db_path = 'naviSsurance_index.db'
if not os.path.exists(db_path):
    print(f"Database file {db_path} does not exist")
    exit(1)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"Tables in database: {tables}")

    # Check if tasks table exists
    if ('tasks',) in tables:
        # Count tasks
        cursor.execute("SELECT COUNT(*) FROM tasks")
        count = cursor.fetchone()[0]
        print(f"Number of tasks in database: {count}")

        if count > 0:
            # Show sample tasks
            cursor.execute("SELECT id, task_text, due_date, category, recurrence, completed FROM tasks LIMIT 5")
            tasks = cursor.fetchall()
            print("Sample tasks:")
            for task in tasks:
                print(f"  ID: {task[0]}, Text: {task[1]}, Due: {task[2]}, Category: {task[3]}, Recurrence: {task[4]}, Completed: {task[5]}")
        else:
            print("No tasks found in database")
    else:
        print("Tasks table does not exist")

    conn.close()

except Exception as e:
    print(f"Error checking database: {e}")
    import traceback
    traceback.print_exc()
