import sqlite3

conn = sqlite3.connect("railpulse.db")
cursor = conn.cursor()

# Get all table names inside railpulse.db
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

print("Tables found in railpulse.db:", tables)
conn.close()