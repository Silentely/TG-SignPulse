import os
import sqlite3

__test__ = False


def main() -> None:
    db_path = ".signer/signs/NiYa.session"

    if not os.path.exists(db_path):
        print(f"File {db_path} not found.")
        return

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, access_hash, type, username FROM peers WHERE id IN (?, ?, ?)",
            (7516512581, -7516512581, -1007516512581),
        )
        rows = cursor.fetchall()

        if rows:
            print("Found matching peers:")
            for row in rows:
                print(
                    f"  ID: {row[0]}, Hash: {row[1]}, Type: {row[2]}, Username: {row[3]}"
                )
        else:
            print("Peer 7516512581 not found in local cache.")

        cursor.execute("SELECT id, type, username FROM peers LIMIT 10")
        print("\nSample peers in DB:")
        for row in cursor.fetchall():
            print(row)

    except sqlite3.OperationalError as e:
        print(f"DB Error: {e}")
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
