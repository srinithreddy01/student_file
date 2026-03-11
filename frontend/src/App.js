import React, { useState, useEffect, useCallback } from "react";
import "./App.css";

const API_URL = window.location.hostname === "localhost"
  ? "http://localhost:5000"
  : "/api";

function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [isRegister, setIsRegister] = useState(false);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const [userId, setUserId] = useState(null);

  const [file, setFile] = useState(null);
  const [files, setFiles] = useState([]);
  const [folders, setFolders] = useState([]);
  const [message, setMessage] = useState("");
  const [msgType, setMsgType] = useState("");

  // Folder navigation
  const [currentFolderId, setCurrentFolderId] = useState(null);
  const [breadcrumb, setBreadcrumb] = useState([]);

  // Modal states
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");

  // Rename state
  const [renamingFolderId, setRenamingFolderId] = useState(null);
  const [renameValue, setRenameValue] = useState("");

  // -------------------------
  // HELPERS
  // -------------------------

  const showMsg = (text, type = "success") => {
    setMessage(text);
    setMsgType(type);
    setTimeout(() => setMessage(""), 4000);
  };

  // -------------------------
  // AUTH
  // -------------------------

  const handleAuth = async () => {
    if (!username || !password) {
      showMsg("Please fill in all fields.", "error");
      return;
    }

    const endpoint = isRegister ? "/register" : "/login";

    try {
      const response = await fetch(API_URL + endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (data.message) {
        showMsg(data.message, "success");
        if (!isRegister) {
          setIsLoggedIn(true);
          setUserId(data.user_id);
        }
      } else {
        showMsg(data.error || "Something went wrong", "error");
      }
    } catch (err) {
      showMsg("Could not connect to server.", "error");
    }
  };

  // -------------------------
  // DATA FETCHING
  // -------------------------

  const fetchContents = useCallback(async () => {
    if (!userId) return;

    try {
      const folderParam = currentFolderId ? `?parent_id=${currentFolderId}` : "";
      const fileParam = currentFolderId ? `?folder_id=${currentFolderId}` : "";

      const [foldersRes, filesRes] = await Promise.all([
        fetch(`${API_URL}/folders/${userId}${folderParam}`),
        fetch(`${API_URL}/files/${userId}${fileParam}`),
      ]);

      const foldersData = await foldersRes.json();
      const filesData = await filesRes.json();

      setFolders(foldersData);
      setFiles(filesData);
    } catch (err) {
      console.error("Failed to fetch contents:", err);
    }
  }, [userId, currentFolderId]);

  const fetchBreadcrumb = useCallback(async () => {
    if (!currentFolderId) {
      setBreadcrumb([]);
      return;
    }

    try {
      const res = await fetch(`${API_URL}/folder-path/${currentFolderId}`);
      const data = await res.json();
      setBreadcrumb(data);
    } catch (err) {
      setBreadcrumb([]);
    }
  }, [currentFolderId]);

  useEffect(() => {
    if (isLoggedIn && userId) {
      fetchContents();
      fetchBreadcrumb();
    }
  }, [isLoggedIn, userId, fetchContents, fetchBreadcrumb]);

  // -------------------------
  // FOLDER ACTIONS
  // -------------------------

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) {
      showMsg("Enter a folder name.", "error");
      return;
    }

    try {
      const res = await fetch(`${API_URL}/folders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newFolderName.trim(),
          user_id: userId,
          parent_id: currentFolderId,
        }),
      });

      const data = await res.json();
      if (data.error) {
        showMsg(data.error, "error");
      } else {
        showMsg("Folder created!", "success");
        setNewFolderName("");
        setShowNewFolder(false);
        fetchContents();
      }
    } catch (err) {
      showMsg("Failed to create folder.", "error");
    }
  };

  const handleDeleteFolder = async (folderId) => {
    if (!window.confirm("Delete this folder and all its contents?")) return;

    try {
      await fetch(`${API_URL}/folders/${folderId}?user_id=${userId}`, {
        method: "DELETE",
      });
      showMsg("Folder deleted.", "success");
      fetchContents();
    } catch (err) {
      showMsg("Failed to delete folder.", "error");
    }
  };

  const handleRenameFolder = async (folderId) => {
    if (!renameValue.trim()) return;

    try {
      await fetch(`${API_URL}/folders/${folderId}/rename`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: renameValue.trim(), user_id: userId }),
      });
      showMsg("Folder renamed!", "success");
      setRenamingFolderId(null);
      setRenameValue("");
      fetchContents();
    } catch (err) {
      showMsg("Failed to rename.", "error");
    }
  };

  const navigateToFolder = (folderId) => {
    setCurrentFolderId(folderId);
  };

  const navigateUp = () => {
    if (breadcrumb.length >= 2) {
      setCurrentFolderId(breadcrumb[breadcrumb.length - 2].id);
    } else {
      setCurrentFolderId(null);
    }
  };

  // -------------------------
  // FILE ACTIONS
  // -------------------------

  const handleUpload = async () => {
    if (!file) {
      showMsg("Please select a file first.", "error");
      return;
    }

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("user_id", userId);
      if (currentFolderId) {
        formData.append("folder_id", currentFolderId);
      }

      const response = await fetch(API_URL + "/upload", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      showMsg(data.message || data.error || "Uploaded!", "success");
      setFile(null);
      const fileInput = document.getElementById("file-input");
      if (fileInput) fileInput.value = "";
      fetchContents();
    } catch (err) {
      showMsg("Upload failed.", "error");
    }
  };

  const handleDelete = async (fileName) => {
    if (!window.confirm(`Delete "${fileName}"?`)) return;

    try {
      await fetch(`${API_URL}/delete/${userId}/${fileName}`, {
        method: "DELETE",
      });
      showMsg("File deleted.", "success");
      fetchContents();
    } catch (err) {
      showMsg("Delete failed.", "error");
    }
  };

  const handleLogout = () => {
    setIsLoggedIn(false);
    setUserId(null);
    setUsername("");
    setPassword("");
    setFiles([]);
    setFolders([]);
    setMessage("");
    setFile(null);
    setCurrentFolderId(null);
    setBreadcrumb([]);
  };

  const getFileIcon = (name) => {
    const ext = name.split(".").pop().toLowerCase();
    if (["jpg", "jpeg", "png", "gif", "svg", "webp"].includes(ext)) return "🖼️";
    if (["pdf"].includes(ext)) return "📄";
    if (["doc", "docx", "txt"].includes(ext)) return "📝";
    if (["xls", "xlsx", "csv"].includes(ext)) return "📊";
    if (["zip", "rar", "7z"].includes(ext)) return "📦";
    if (["mp4", "avi", "mov"].includes(ext)) return "🎬";
    if (["mp3", "wav"].includes(ext)) return "🎵";
    if (["py", "js", "html", "css", "java", "c", "cpp"].includes(ext)) return "💻";
    if (["ppt", "pptx"].includes(ext)) return "📎";
    return "📁";
  };

  // -------------------------
  // AUTH UI
  // -------------------------

  if (!isLoggedIn) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <h1>{isRegister ? "Create Account" : "Welcome Back"}</h1>
          <p className="auth-subtitle">
            {isRegister
              ? "Register to start uploading files"
              : "Sign in to your account"}
          </p>

          <div className="form-group">
            <label>Username</label>
            <input
              placeholder="Enter your username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAuth()}
            />
          </div>

          <div className="form-group">
            <label>Password</label>
            <input
              type="password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAuth()}
            />
          </div>

          <button className="btn btn-primary" onClick={handleAuth}>
            {isRegister ? "Create Account" : "Sign In"}
          </button>

          <button
            className="btn btn-link"
            onClick={() => {
              setIsRegister(!isRegister);
              setMessage("");
            }}
          >
            {isRegister
              ? "Already have an account? Sign in"
              : "Don't have an account? Register"}
          </button>

          {message && <div className={`msg ${msgType}`}>{message}</div>}
        </div>
      </div>
    );
  }

  // -------------------------
  // DASHBOARD UI
  // -------------------------

  return (
    <div className="dashboard">
      {/* Header */}
      <div className="dash-header">
        <div>
          <h1>📂 My Files</h1>
          <p className="welcome">Welcome, {username}</p>
        </div>
        <button className="btn-logout" onClick={handleLogout}>
          Logout
        </button>
      </div>

      {/* Breadcrumb */}
      <div className="breadcrumb">
        <span
          className={`crumb ${!currentFolderId ? "active" : ""}`}
          onClick={() => setCurrentFolderId(null)}
        >
          🏠 Home
        </span>
        {breadcrumb.map((b, i) => (
          <React.Fragment key={b.id}>
            <span className="crumb-sep">/</span>
            <span
              className={`crumb ${i === breadcrumb.length - 1 ? "active" : ""}`}
              onClick={() => navigateToFolder(b.id)}
            >
              {b.name}
            </span>
          </React.Fragment>
        ))}
      </div>

      {/* Action bar */}
      <div className="action-bar">
        <button
          className="btn-action"
          onClick={() => setShowNewFolder(!showNewFolder)}
        >
          ➕ New Folder
        </button>
        {currentFolderId && (
          <button className="btn-action back" onClick={navigateUp}>
            ⬅ Back
          </button>
        )}
      </div>

      {/* New folder input */}
      {showNewFolder && (
        <div className="new-folder-row">
          <input
            className="folder-input"
            placeholder="Folder name..."
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreateFolder()}
            autoFocus
          />
          <button className="btn-action create" onClick={handleCreateFolder}>
            Create
          </button>
          <button
            className="btn-action"
            onClick={() => {
              setShowNewFolder(false);
              setNewFolderName("");
            }}
          >
            Cancel
          </button>
        </div>
      )}

      {/* Upload Card */}
      <div className="upload-card">
        <div className="upload-zone">
          <input
            type="file"
            id="file-input"
            onChange={(e) => setFile(e.target.files[0])}
          />
          <div className="upload-icon">☁️</div>
          {file ? (
            <div className="file-name-selected">{file.name}</div>
          ) : (
            <div className="label">Click to choose a file</div>
          )}
        </div>
        <button
          className="btn-upload"
          onClick={handleUpload}
          disabled={!file}
        >
          ⬆ Upload{currentFolderId ? " to this folder" : ""}
        </button>
      </div>

      {/* Message */}
      {message && (
        <div className={`msg ${msgType}`} style={{ marginBottom: "1.5rem" }}>
          {message}
        </div>
      )}

      {/* Folders Grid */}
      {folders.length > 0 && (
        <div className="section">
          <h2>📁 Folders ({folders.length})</h2>
          <div className="folder-grid">
            {folders.map((folder) => (
              <div
                key={folder.id}
                className="folder-card"
                onDoubleClick={() => navigateToFolder(folder.id)}
              >
                {renamingFolderId === folder.id ? (
                  <div className="rename-row">
                    <input
                      className="rename-input"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleRenameFolder(folder.id);
                        if (e.key === "Escape") setRenamingFolderId(null);
                      }}
                      autoFocus
                    />
                    <button
                      className="btn-mini save"
                      onClick={() => handleRenameFolder(folder.id)}
                    >
                      ✓
                    </button>
                  </div>
                ) : (
                  <>
                    <div
                      className="folder-card-main"
                      onClick={() => navigateToFolder(folder.id)}
                    >
                      <span className="folder-emoji">📁</span>
                      <span className="folder-name">{folder.name}</span>
                    </div>
                    <div className="folder-actions">
                      <button
                        className="btn-mini"
                        title="Rename"
                        onClick={(e) => {
                          e.stopPropagation();
                          setRenamingFolderId(folder.id);
                          setRenameValue(folder.name);
                        }}
                      >
                        ✏️
                      </button>
                      <button
                        className="btn-mini delete"
                        title="Delete"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteFolder(folder.id);
                        }}
                      >
                        🗑️
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Files List */}
      <div className="section">
        <h2>📄 Files ({files.length})</h2>

        {files.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">📭</div>
            <p>No files here yet</p>
          </div>
        ) : (
          <ul className="file-list">
            {files.map((f) => (
              <li key={f.id} className="file-item">
                <div className="file-info">
                  <div className="file-icon">{getFileIcon(f.filename)}</div>
                  <div className="file-details">
                    <span className="file-name">{f.filename}</span>
                    {f.uploaded_at && (
                      <span className="file-date">
                        {new Date(f.uploaded_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                </div>
                <div className="file-actions">
                  <a
                    className="btn-icon"
                    href={`${API_URL}/download/${f.filename}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    ⬇ Download
                  </a>
                  <button
                    className="btn-icon delete"
                    onClick={() => handleDelete(f.filename)}
                  >
                    ✕ Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default App;