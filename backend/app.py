import bcrypt
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import sqlite3
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "database.db")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ------------------------
# DATABASE SETUP
# ------------------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            parent_id INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(parent_id) REFERENCES folders(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            user_id INTEGER,
            folder_id INTEGER DEFAULT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(folder_id) REFERENCES folders(id)
        )
    """)

    # Migrate: add folder_id and uploaded_at to existing files table
    cursor.execute("PRAGMA table_info(files)")
    columns = [col[1] for col in cursor.fetchall()]

    if "folder_id" not in columns:
        cursor.execute("ALTER TABLE files ADD COLUMN folder_id INTEGER DEFAULT NULL")

    if "uploaded_at" not in columns:
        cursor.execute("ALTER TABLE files ADD COLUMN uploaded_at TIMESTAMP DEFAULT NULL")

    conn.commit()
    conn.close()

init_db()

# ------------------------
# AUTH ROUTES
# ------------------------

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    hashed_password = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    )

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, hashed_password)
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "User registered successfully!"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 400


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, password FROM users WHERE username=?",
        (username,)
    )

    user = cursor.fetchone()
    conn.close()

    if user and bcrypt.checkpw(
        password.encode("utf-8"),
        user[1]
    ):
        return jsonify({
            "message": "Login successful",
            "user_id": user[0]
        })
    else:
        return jsonify({"error": "Invalid credentials"}), 401

# ------------------------
# FOLDER ROUTES
# ------------------------

@app.route("/folders/<int:user_id>", methods=["GET"])
def list_folders(user_id):
    parent_id = request.args.get("parent_id", None)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if parent_id is None or parent_id == "null":
        cursor.execute(
            "SELECT id, name, created_at FROM folders WHERE user_id=? AND parent_id IS NULL",
            (user_id,)
        )
    else:
        cursor.execute(
            "SELECT id, name, created_at FROM folders WHERE user_id=? AND parent_id=?",
            (user_id, int(parent_id))
        )

    folders = cursor.fetchall()
    conn.close()

    return jsonify([
        {"id": f[0], "name": f[1], "created_at": f[2]}
        for f in folders
    ])


@app.route("/folders", methods=["POST"])
def create_folder():
    data = request.json
    name = data.get("name", "").strip()
    user_id = data.get("user_id")
    parent_id = data.get("parent_id", None)

    if not name:
        return jsonify({"error": "Folder name is required"}), 400

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check for duplicate name in same parent
    if parent_id is None:
        cursor.execute(
            "SELECT id FROM folders WHERE name=? AND user_id=? AND parent_id IS NULL",
            (name, user_id)
        )
    else:
        cursor.execute(
            "SELECT id FROM folders WHERE name=? AND user_id=? AND parent_id=?",
            (name, user_id, parent_id)
        )

    if cursor.fetchone():
        conn.close()
        return jsonify({"error": "Folder already exists"}), 400

    cursor.execute(
        "INSERT INTO folders (name, user_id, parent_id) VALUES (?, ?, ?)",
        (name, user_id, parent_id)
    )
    conn.commit()
    folder_id = cursor.lastrowid
    conn.close()

    return jsonify({"message": "Folder created!", "folder_id": folder_id})


@app.route("/folders/<int:folder_id>", methods=["DELETE"])
def delete_folder(folder_id):
    user_id = request.args.get("user_id")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Verify ownership
    cursor.execute(
        "SELECT id FROM folders WHERE id=? AND user_id=?",
        (folder_id, user_id)
    )
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "Folder not found"}), 404

    # Delete all files in folder (and subfolders recursively)
    _delete_folder_recursive(cursor, folder_id, user_id)

    conn.commit()
    conn.close()

    return jsonify({"message": "Folder deleted!"})


def _delete_folder_recursive(cursor, folder_id, user_id):
    # Delete files in this folder from disk
    cursor.execute(
        "SELECT filename FROM files WHERE folder_id=? AND user_id=?",
        (folder_id, user_id)
    )
    for row in cursor.fetchall():
        file_path = os.path.join(UPLOAD_FOLDER, row[0])
        if os.path.exists(file_path):
            os.remove(file_path)

    # Delete file records
    cursor.execute(
        "DELETE FROM files WHERE folder_id=? AND user_id=?",
        (folder_id, user_id)
    )

    # Find child folders
    cursor.execute(
        "SELECT id FROM folders WHERE parent_id=? AND user_id=?",
        (folder_id, user_id)
    )
    children = cursor.fetchall()
    for child in children:
        _delete_folder_recursive(cursor, child[0], user_id)

    # Delete this folder
    cursor.execute("DELETE FROM folders WHERE id=?", (folder_id,))


@app.route("/folders/<int:folder_id>/rename", methods=["PUT"])
def rename_folder(folder_id):
    data = request.json
    new_name = data.get("name", "").strip()
    user_id = data.get("user_id")

    if not new_name:
        return jsonify({"error": "Name is required"}), 400

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE folders SET name=? WHERE id=? AND user_id=?",
        (new_name, folder_id, user_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "Folder renamed!"})


@app.route("/folder-path/<int:folder_id>", methods=["GET"])
def get_folder_path(folder_id):
    """Return the breadcrumb path for a folder"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    path = []
    current_id = folder_id

    while current_id is not None:
        cursor.execute(
            "SELECT id, name, parent_id FROM folders WHERE id=?",
            (current_id,)
        )
        row = cursor.fetchone()
        if row:
            path.append({"id": row[0], "name": row[1]})
            current_id = row[2]
        else:
            break

    conn.close()
    path.reverse()
    return jsonify(path)


# ------------------------
# FILE ROUTES
# ------------------------

@app.route("/upload", methods=["POST"])
def upload_file():
    user_id = request.form.get("user_id")
    folder_id = request.form.get("folder_id", None)

    if folder_id == "" or folder_id == "null":
        folder_id = None

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    filename = secure_filename(file.filename)
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    # Handle duplicate filenames on disk
    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(file_path):
        filename = f"{base}_{counter}{ext}"
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        counter += 1

    file.save(file_path)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO files (filename, user_id, folder_id) VALUES (?, ?, ?)",
        (filename, user_id, folder_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "File uploaded successfully!"})


@app.route("/")
def home():
    return "Backend is running!"


@app.route("/files/<int:user_id>", methods=["GET"])
def list_files(user_id):
    folder_id = request.args.get("folder_id", None)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if folder_id is None or folder_id == "null":
        cursor.execute(
            "SELECT id, filename, uploaded_at FROM files WHERE user_id=? AND folder_id IS NULL",
            (user_id,)
        )
    else:
        cursor.execute(
            "SELECT id, filename, uploaded_at FROM files WHERE user_id=? AND folder_id=?",
            (user_id, int(folder_id))
        )

    files = cursor.fetchall()
    conn.close()

    return jsonify([
        {"id": f[0], "filename": f[1], "uploaded_at": f[2]}
        for f in files
    ])


@app.route("/files/<int:file_id>/move", methods=["PUT"])
def move_file(file_id):
    data = request.json
    user_id = data.get("user_id")
    folder_id = data.get("folder_id", None)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE files SET folder_id=? WHERE id=? AND user_id=?",
        (folder_id, file_id, user_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "File moved!"})


@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    filename = secure_filename(filename)
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    return send_file(file_path, as_attachment=True)


@app.route("/delete/<int:user_id>/<filename>", methods=["DELETE"])
def delete_file(user_id, filename):
    filename = secure_filename(filename)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM files WHERE filename=? AND user_id=?",
        (filename, user_id)
    )

    file = cursor.fetchone()

    if not file:
        conn.close()
        return jsonify({"error": "Not allowed"}), 403

    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    cursor.execute(
        "DELETE FROM files WHERE filename=? AND user_id=?",
        (filename, user_id)
    )

    conn.commit()
    conn.close()

    return jsonify({"message": "File deleted successfully!"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)