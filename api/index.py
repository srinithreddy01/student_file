import bcrypt
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import os
import psycopg2
from werkzeug.utils import secure_filename
import requests
import uuid

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ------------------------
# DATABASE (Vercel Postgres)
# ------------------------

def get_db():
    db_url = os.environ.get('POSTGRES_URL', '')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    conn = psycopg2.connect(db_url)
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password BYTEA NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id),
            parent_id INTEGER REFERENCES folders(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id SERIAL PRIMARY KEY,
            filename TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            folder_id INTEGER REFERENCES folders(id),
            blob_url TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


try:
    init_db()
except Exception as e:
    print(f"DB init will retry on first request: {e}")

# ------------------------
# VERCEL BLOB HELPERS
# ------------------------

BLOB_API = "https://blob.vercel-storage.com"


def upload_blob(file_data, filename):
    token = os.environ.get('BLOB_READ_WRITE_TOKEN', '')
    resp = requests.put(
        f"{BLOB_API}/{filename}",
        data=file_data,
        headers={
            "Authorization": f"Bearer {token}",
            "x-api-version": "7",
            "Content-Type": "application/octet-stream",
        }
    )
    return resp.json()


def delete_blob(url):
    token = os.environ.get('BLOB_READ_WRITE_TOKEN', '')
    requests.post(
        f"{BLOB_API}/delete",
        json={"urls": [url]},
        headers={
            "Authorization": f"Bearer {token}",
            "x-api-version": "7",
            "Content-Type": "application/json",
        }
    )

# ------------------------
# AUTH ROUTES
# ------------------------

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (%s, %s)",
            (username, hashed)
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "User registered successfully!"})
    except psycopg2.IntegrityError:
        return jsonify({"error": "Username already exists"}), 400


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, password FROM users WHERE username=%s",
        (username,)
    )
    user = cursor.fetchone()
    conn.close()

    if user and bcrypt.checkpw(password.encode("utf-8"), bytes(user[1])):
        return jsonify({"message": "Login successful", "user_id": user[0]})
    else:
        return jsonify({"error": "Invalid credentials"}), 401

# ------------------------
# FOLDER ROUTES
# ------------------------

@app.route("/api/folders/<int:user_id>", methods=["GET"])
def list_folders(user_id):
    parent_id = request.args.get("parent_id", None)

    conn = get_db()
    cursor = conn.cursor()

    if parent_id is None or parent_id == "null":
        cursor.execute(
            "SELECT id, name, created_at FROM folders WHERE user_id=%s AND parent_id IS NULL",
            (user_id,)
        )
    else:
        cursor.execute(
            "SELECT id, name, created_at FROM folders WHERE user_id=%s AND parent_id=%s",
            (user_id, int(parent_id))
        )

    folders = cursor.fetchall()
    conn.close()

    return jsonify([
        {"id": f[0], "name": f[1], "created_at": str(f[2]) if f[2] else None}
        for f in folders
    ])


@app.route("/api/folders", methods=["POST"])
def create_folder():
    data = request.json
    name = data.get("name", "").strip()
    user_id = data.get("user_id")
    parent_id = data.get("parent_id", None)

    if not name:
        return jsonify({"error": "Folder name is required"}), 400

    conn = get_db()
    cursor = conn.cursor()

    if parent_id is None:
        cursor.execute(
            "SELECT id FROM folders WHERE name=%s AND user_id=%s AND parent_id IS NULL",
            (name, user_id)
        )
    else:
        cursor.execute(
            "SELECT id FROM folders WHERE name=%s AND user_id=%s AND parent_id=%s",
            (name, user_id, parent_id)
        )

    if cursor.fetchone():
        conn.close()
        return jsonify({"error": "Folder already exists"}), 400

    cursor.execute(
        "INSERT INTO folders (name, user_id, parent_id) VALUES (%s, %s, %s) RETURNING id",
        (name, user_id, parent_id)
    )
    folder_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()

    return jsonify({"message": "Folder created!", "folder_id": folder_id})


@app.route("/api/folders/<int:folder_id>", methods=["DELETE"])
def delete_folder(folder_id):
    user_id = request.args.get("user_id")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM folders WHERE id=%s AND user_id=%s",
        (folder_id, user_id)
    )
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "Folder not found"}), 404

    _delete_folder_recursive(cursor, folder_id, user_id)
    conn.commit()
    conn.close()

    return jsonify({"message": "Folder deleted!"})


def _delete_folder_recursive(cursor, folder_id, user_id):
    # Delete blob files
    cursor.execute(
        "SELECT blob_url FROM files WHERE folder_id=%s AND user_id=%s",
        (folder_id, user_id)
    )
    for row in cursor.fetchall():
        if row[0]:
            try:
                delete_blob(row[0])
            except Exception:
                pass

    cursor.execute(
        "DELETE FROM files WHERE folder_id=%s AND user_id=%s",
        (folder_id, user_id)
    )

    cursor.execute(
        "SELECT id FROM folders WHERE parent_id=%s AND user_id=%s",
        (folder_id, user_id)
    )
    children = cursor.fetchall()
    for child in children:
        _delete_folder_recursive(cursor, child[0], user_id)

    cursor.execute("DELETE FROM folders WHERE id=%s", (folder_id,))


@app.route("/api/folders/<int:folder_id>/rename", methods=["PUT"])
def rename_folder(folder_id):
    data = request.json
    new_name = data.get("name", "").strip()
    user_id = data.get("user_id")

    if not new_name:
        return jsonify({"error": "Name is required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE folders SET name=%s WHERE id=%s AND user_id=%s",
        (new_name, folder_id, user_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "Folder renamed!"})


@app.route("/api/folder-path/<int:folder_id>", methods=["GET"])
def get_folder_path(folder_id):
    conn = get_db()
    cursor = conn.cursor()

    path = []
    current_id = folder_id

    while current_id is not None:
        cursor.execute(
            "SELECT id, name, parent_id FROM folders WHERE id=%s",
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

@app.route("/api/upload", methods=["POST"])
def upload_file():
    user_id = request.form.get("user_id")
    folder_id = request.form.get("folder_id", None)

    if folder_id == "" or folder_id == "null":
        folder_id = None

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    filename = secure_filename(file.filename)

    # Upload to Vercel Blob with unique path
    file_data = file.read()
    blob_path = f"{user_id}/{uuid.uuid4().hex}_{filename}"
    blob_result = upload_blob(file_data, blob_path)
    blob_url = blob_result.get("url")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO files (filename, user_id, folder_id, blob_url) VALUES (%s, %s, %s, %s)",
        (filename, user_id, folder_id, blob_url)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "File uploaded successfully!"})


@app.route("/api/", methods=["GET"])
def home():
    return jsonify({"status": "Backend is running on Vercel!"})


@app.route("/api/files/<int:user_id>", methods=["GET"])
def list_files(user_id):
    folder_id = request.args.get("folder_id", None)

    conn = get_db()
    cursor = conn.cursor()

    if folder_id is None or folder_id == "null":
        cursor.execute(
            "SELECT id, filename, uploaded_at FROM files WHERE user_id=%s AND folder_id IS NULL",
            (user_id,)
        )
    else:
        cursor.execute(
            "SELECT id, filename, uploaded_at FROM files WHERE user_id=%s AND folder_id=%s",
            (user_id, int(folder_id))
        )

    files = cursor.fetchall()
    conn.close()

    return jsonify([
        {"id": f[0], "filename": f[1], "uploaded_at": str(f[2]) if f[2] else None}
        for f in files
    ])


@app.route("/api/files/<int:file_id>/move", methods=["PUT"])
def move_file(file_id):
    data = request.json
    user_id = data.get("user_id")
    folder_id = data.get("folder_id", None)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE files SET folder_id=%s WHERE id=%s AND user_id=%s",
        (folder_id, file_id, user_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "File moved!"})


@app.route("/api/download/<filename>", methods=["GET"])
def download_file(filename):
    filename = secure_filename(filename)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT blob_url FROM files WHERE filename=%s",
        (filename,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row or not row[0]:
        return jsonify({"error": "File not found"}), 404

    return redirect(row[0])


@app.route("/api/delete/<int:user_id>/<filename>", methods=["DELETE"])
def delete_file(user_id, filename):
    filename = secure_filename(filename)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, blob_url FROM files WHERE filename=%s AND user_id=%s",
        (filename, user_id)
    )
    file = cursor.fetchone()

    if not file:
        conn.close()
        return jsonify({"error": "Not allowed"}), 403

    if file[1]:
        try:
            delete_blob(file[1])
        except Exception:
            pass

    cursor.execute(
        "DELETE FROM files WHERE filename=%s AND user_id=%s",
        (filename, user_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "File deleted successfully!"})
