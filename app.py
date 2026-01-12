#!/usr/bin/env python3
"""
Boswell v2 API - Git-Style Memory Architecture
PostgreSQL version with multi-tenant support + Encryption (Phase 2)
"""

import psycopg2
import psycopg2.extras
import hashlib
import json
import os
from datetime import datetime
from flask import Flask, request, jsonify, g
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Encryption support (Phase 2)
ENCRYPTION_ENABLED = os.environ.get('ENCRYPTION_ENABLED', 'false').lower() == 'true'
CREDENTIALS_PATH = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'service-account-key.json')

_encryption_service = None
_active_dek = None  # (key_id, wrapped_dek)

def get_encryption_service():
    """Get or initialize the encryption service."""
    global _encryption_service
    if _encryption_service is None and ENCRYPTION_ENABLED:
        try:
            from encryption_service import get_encryption_service as init_service
            _encryption_service = init_service(CREDENTIALS_PATH)
            print(f"[STARTUP] Encryption service initialized", file=sys.stderr)
        except Exception as e:
            print(f"[STARTUP] WARNING: Encryption service failed to initialize: {e}", file=sys.stderr)
    return _encryption_service

def get_active_dek():
    """Get the active DEK for the current tenant."""
    global _active_dek
    if _active_dek is None and ENCRYPTION_ENABLED:
        cur = get_cursor()
        cur.execute(
            "SELECT key_id, wrapped_key FROM data_encryption_keys WHERE tenant_id = %s AND status = 'active' LIMIT 1",
            (DEFAULT_TENANT,)
        )
        row = cur.fetchone()
        cur.close()
        if row:
            _active_dek = (row['key_id'], bytes(row['wrapped_key']))
    return _active_dek

# Database URL from environment (Railway provides this)
DATABASE_URL = os.environ.get('DATABASE_URL')

# Startup logging for debugging
import sys
print(f"[STARTUP] DATABASE_URL set: {bool(DATABASE_URL)}", file=sys.stderr)
if DATABASE_URL:
    # Log sanitized URL (hide password)
    from urllib.parse import urlparse
    parsed = urlparse(DATABASE_URL)
    safe_url = f"{parsed.scheme}://{parsed.username}:***@{parsed.hostname}:{parsed.port}{parsed.path}"
    print(f"[STARTUP] Database host: {parsed.hostname}:{parsed.port}", file=sys.stderr)

# Default tenant for single-tenant mode (Steve Krontz)
DEFAULT_TENANT = '00000000-0000-0000-0000-000000000001'

# Project to branch mapping for auto-routing
PROJECT_BRANCH_MAP = {
    'tint-atlanta': 'tint-atlanta',
    'tint-empire': 'tint-empire',
    'iris': 'iris',
    'family': 'family',
    'command-center': 'command-center',
    'boswell': 'boswell',
    'default': 'command-center'
}

def get_db():
    """Get database connection for current request context."""
    if 'db' not in g:
        if not DATABASE_URL:
            raise Exception("DATABASE_URL environment variable not set")
        # Add connection timeout to prevent hanging
        g.db = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        g.db.autocommit = False
        # Set tenant context for RLS
        cur = g.db.cursor()
        cur.execute(f"SET app.current_tenant = '{DEFAULT_TENANT}'")
        cur.close()
    return g.db

def get_cursor():
    """Get a cursor with dict-like row access."""
    db = get_db()
    return db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

@app.teardown_appcontext
def close_db(exception):
    """Close database connection at end of request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def compute_hash(content):
    """Compute SHA-256 hash for content-addressable storage."""
    if isinstance(content, str):
        content = content.encode('utf-8')
    return hashlib.sha256(content).hexdigest()

def get_current_head(branch='command-center'):
    """Get the current HEAD commit for a branch."""
    cur = get_cursor()
    cur.execute(
        'SELECT head_commit FROM branches WHERE name = %s AND tenant_id = %s',
        (branch, DEFAULT_TENANT)
    )
    row = cur.fetchone()
    cur.close()
    return row['head_commit'] if row else None

def get_branch_for_project(project):
    """Map project name to cognitive branch."""
    if project in PROJECT_BRANCH_MAP:
        return PROJECT_BRANCH_MAP[project]
    for key in PROJECT_BRANCH_MAP:
        if key in project.lower():
            return PROJECT_BRANCH_MAP[key]
    return PROJECT_BRANCH_MAP['default']

# ==================== API ENDPOINTS ====================

@app.route('/', methods=['GET'])
@app.route('/v2/', methods=['GET'])
def health_check():
    """Health check endpoint."""
    try:
        cur = get_cursor()
        cur.execute('SELECT COUNT(*) as count FROM branches WHERE tenant_id = %s', (DEFAULT_TENANT,))
        branch_count = cur.fetchone()['count']
        cur.execute('SELECT COUNT(*) as count FROM commits WHERE tenant_id = %s', (DEFAULT_TENANT,))
        commit_count = cur.fetchone()['count']
        cur.close()
        # Check encryption status
        encryption_status = 'disabled'
        if ENCRYPTION_ENABLED:
            encryption_status = 'enabled'
            if get_active_dek():
                encryption_status = 'active'

        return jsonify({
            'status': 'ok',
            'service': 'boswell-v2',
            'version': '2.7.0-encrypted',
            'platform': 'railway',
            'database': 'postgres',
            'encryption': encryption_status,
            'branches': branch_count,
            'commits': commit_count,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/v2/head', methods=['GET'])
def get_head():
    """Get current HEAD state for a branch."""
    branch = request.args.get('branch', 'command-center')
    cur = get_cursor()

    cur.execute('SELECT * FROM branches WHERE name = %s AND tenant_id = %s', (branch, DEFAULT_TENANT))
    branch_info = cur.fetchone()

    if not branch_info:
        cur.close()
        return jsonify({'error': f'Branch {branch} not found'}), 404

    head_commit = branch_info['head_commit']
    commit_info = None
    if head_commit and head_commit != 'GENESIS':
        cur.execute('SELECT * FROM commits WHERE commit_hash = %s AND tenant_id = %s', (head_commit, DEFAULT_TENANT))
        commit_row = cur.fetchone()
        if commit_row:
            commit_info = dict(commit_row)

    cur.close()
    return jsonify({
        'branch': branch,
        'head_commit': head_commit,
        'commit': commit_info,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

@app.route('/v2/checkout', methods=['POST'])
def checkout_branch():
    """Switch to a different branch."""
    data = request.get_json() or {}
    branch = data.get('branch')

    if not branch:
        return jsonify({'error': 'Branch name required'}), 400

    cur = get_cursor()
    cur.execute('SELECT * FROM branches WHERE name = %s AND tenant_id = %s', (branch, DEFAULT_TENANT))
    branch_info = cur.fetchone()
    cur.close()

    if not branch_info:
        return jsonify({'error': f'Branch {branch} not found'}), 404

    return jsonify({
        'status': 'checked_out',
        'branch': branch,
        'head_commit': branch_info['head_commit']
    })

@app.route('/v2/branches', methods=['GET'])
def list_branches():
    """List all cognitive branches."""
    cur = get_cursor()
    cur.execute('SELECT * FROM branches WHERE tenant_id = %s ORDER BY name', (DEFAULT_TENANT,))
    branches = [dict(row) for row in cur.fetchall()]
    cur.close()
    return jsonify({'branches': branches, 'count': len(branches)})

@app.route('/v2/branch', methods=['POST'])
def create_branch():
    """Create a new cognitive branch."""
    data = request.get_json() or {}
    name = data.get('name')
    from_branch = data.get('from', 'command-center')

    if not name:
        return jsonify({'error': 'Branch name required'}), 400

    db = get_db()
    cur = get_cursor()

    cur.execute('SELECT name FROM branches WHERE name = %s AND tenant_id = %s', (name, DEFAULT_TENANT))
    if cur.fetchone():
        cur.close()
        return jsonify({'error': f'Branch {name} already exists'}), 409

    cur.execute('SELECT head_commit FROM branches WHERE name = %s AND tenant_id = %s', (from_branch, DEFAULT_TENANT))
    source = cur.fetchone()
    head_commit = source['head_commit'] if source else 'GENESIS'

    now = datetime.utcnow().isoformat() + 'Z'
    cur.execute(
        '''INSERT INTO branches (tenant_id, name, head_commit, created_at)
           VALUES (%s, %s, %s, %s)''',
        (DEFAULT_TENANT, name, head_commit, now)
    )
    db.commit()
    cur.close()

    return jsonify({
        'status': 'created',
        'branch': name,
        'from': from_branch,
        'head_commit': head_commit
    }), 201

@app.route('/v2/commit', methods=['POST'])
def create_commit():
    """Commit a memory to the repository."""
    data = request.get_json() or {}
    content = data.get('content')
    message = data.get('message', 'Memory commit')
    branch = data.get('branch', 'command-center')
    author = data.get('author', 'claude')
    memory_type = data.get('type', 'memory')
    tags = data.get('tags', [])

    if not content:
        return jsonify({'error': 'Content required'}), 400

    db = get_db()
    cur = get_cursor()
    now = datetime.utcnow().isoformat() + 'Z'

    content_str = json.dumps(content) if isinstance(content, dict) else str(content)
    blob_hash = compute_hash(content_str)

    # Insert blob with encryption if enabled
    encryption_service = get_encryption_service()
    dek_info = get_active_dek()

    if ENCRYPTION_ENABLED and encryption_service and dek_info:
        # Encrypt the content
        key_id, wrapped_dek = dek_info
        plaintext_dek = encryption_service.unwrap_dek(key_id, wrapped_dek)
        ciphertext, nonce = encryption_service.encrypt(content_str, plaintext_dek)

        cur.execute(
            '''INSERT INTO blobs (blob_hash, tenant_id, content, content_encrypted, nonce, encryption_key_id, content_type, created_at, byte_size)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (blob_hash) DO NOTHING''',
            (blob_hash, DEFAULT_TENANT, content_str, psycopg2.Binary(ciphertext), psycopg2.Binary(nonce), key_id, memory_type, now, len(content_str))
        )
    else:
        # Fallback: store unencrypted
        cur.execute(
            '''INSERT INTO blobs (blob_hash, tenant_id, content, content_type, created_at, byte_size)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (blob_hash) DO NOTHING''',
            (blob_hash, DEFAULT_TENANT, content_str, memory_type, now, len(content_str))
        )

    tree_hash = compute_hash(f"{branch}:{blob_hash}:{now}")
    cur.execute(
        '''INSERT INTO tree_entries (tenant_id, tree_hash, name, blob_hash, mode)
           VALUES (%s, %s, %s, %s, %s)''',
        (DEFAULT_TENANT, tree_hash, message[:100], blob_hash, memory_type)
    )

    cur.execute('SELECT head_commit FROM branches WHERE name = %s AND tenant_id = %s', (branch, DEFAULT_TENANT))
    branch_row = cur.fetchone()
    parent_hash = branch_row['head_commit'] if branch_row else None
    if parent_hash == 'GENESIS':
        parent_hash = None

    commit_data = f"{tree_hash}:{parent_hash}:{message}:{now}"
    commit_hash = compute_hash(commit_data)

    cur.execute(
        '''INSERT INTO commits (commit_hash, tenant_id, tree_hash, parent_hash, author, message, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)''',
        (commit_hash, DEFAULT_TENANT, tree_hash, parent_hash, author, message, now)
    )

    cur.execute(
        'UPDATE branches SET head_commit = %s WHERE name = %s AND tenant_id = %s',
        (commit_hash, branch, DEFAULT_TENANT)
    )

    for tag in tags:
        tag_str = tag if isinstance(tag, str) else str(tag)
        cur.execute(
            '''INSERT INTO tags (tenant_id, blob_hash, tag, created_at)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (tenant_id, blob_hash, tag) DO NOTHING''',
            (DEFAULT_TENANT, blob_hash, tag_str, now)
        )

    db.commit()
    cur.close()

    return jsonify({
        'status': 'committed',
        'commit_hash': commit_hash,
        'blob_hash': blob_hash,
        'tree_hash': tree_hash,
        'branch': branch,
        'message': message
    }), 201

@app.route('/v2/log', methods=['GET'])
def get_log():
    """Get commit history for a branch."""
    branch = request.args.get('branch', 'command-center')
    limit = request.args.get('limit', 20, type=int)

    cur = get_cursor()
    cur.execute('SELECT head_commit FROM branches WHERE name = %s AND tenant_id = %s', (branch, DEFAULT_TENANT))
    branch_row = cur.fetchone()

    if not branch_row:
        cur.close()
        return jsonify({'branch': branch, 'commits': [], 'count': 0})

    head_commit = branch_row['head_commit']
    if head_commit == 'GENESIS':
        cur.close()
        return jsonify({'branch': branch, 'head': 'GENESIS', 'commits': [], 'count': 0})

    commits = []
    current_hash = head_commit

    while current_hash and len(commits) < limit:
        cur.execute('SELECT * FROM commits WHERE commit_hash = %s AND tenant_id = %s', (current_hash, DEFAULT_TENANT))
        commit = cur.fetchone()
        if not commit:
            break
        commits.append(dict(commit))
        current_hash = commit['parent_hash']

    cur.close()
    return jsonify({'branch': branch, 'commits': commits, 'count': len(commits)})

@app.route('/v2/search', methods=['GET'])
def search_memories():
    """Search memories across branches."""
    query = request.args.get('q', '')
    memory_type = request.args.get('type')
    limit = request.args.get('limit', 20, type=int)

    if not query:
        return jsonify({'error': 'Search query required'}), 400

    cur = get_cursor()

    sql = '''
        SELECT DISTINCT b.blob_hash, b.content, b.content_type, b.created_at,
               c.commit_hash, c.message, c.author
        FROM blobs b
        JOIN tree_entries t ON b.blob_hash = t.blob_hash AND b.tenant_id = t.tenant_id
        JOIN commits c ON t.tree_hash = c.tree_hash AND t.tenant_id = c.tenant_id
        WHERE b.content LIKE %s AND b.tenant_id = %s
    '''
    params = [f'%{query}%', DEFAULT_TENANT]

    if memory_type:
        sql += ' AND b.content_type = %s'
        params.append(memory_type)

    sql += ' ORDER BY b.created_at DESC LIMIT %s'
    params.append(limit)

    cur.execute(sql, params)
    results = []

    for row in cur.fetchall():
        content = row['content']
        results.append({
            'blob_hash': row['blob_hash'],
            'content': content[:500] + '...' if len(content) > 500 else content,
            'content_type': row['content_type'],
            'created_at': str(row['created_at']) if row['created_at'] else None,
            'commit_hash': row['commit_hash'],
            'message': row['message'],
            'author': row['author']
        })

    cur.close()
    return jsonify({'query': query, 'results': results, 'count': len(results)})

def decrypt_blob_content(blob):
    """Decrypt blob content if encrypted, otherwise return plaintext."""
    # Check if blob has encrypted content
    if blob.get('content_encrypted') and blob.get('nonce') and blob.get('encryption_key_id'):
        encryption_service = get_encryption_service()
        if encryption_service:
            # Get the DEK for this blob
            cur = get_cursor()
            cur.execute(
                "SELECT wrapped_key FROM data_encryption_keys WHERE key_id = %s",
                (blob['encryption_key_id'],)
            )
            dek_row = cur.fetchone()
            cur.close()

            if dek_row:
                wrapped_dek = bytes(dek_row['wrapped_key'])
                ciphertext = bytes(blob['content_encrypted'])
                nonce = bytes(blob['nonce'])
                return encryption_service.decrypt_with_wrapped_dek(
                    ciphertext, nonce, blob['encryption_key_id'], wrapped_dek
                )
    # Fallback to plaintext content
    return blob.get('content', '')


@app.route('/v2/recall', methods=['GET'])
def recall_memory():
    """Recall a specific memory by hash."""
    blob_hash = request.args.get('hash')
    commit_hash = request.args.get('commit')

    cur = get_cursor()

    if blob_hash:
        cur.execute('SELECT * FROM blobs WHERE blob_hash = %s AND tenant_id = %s', (blob_hash, DEFAULT_TENANT))
        blob = cur.fetchone()
        if not blob:
            cur.close()
            return jsonify({'error': 'Memory not found'}), 404
        cur.close()

        # Decrypt content if needed
        content = decrypt_blob_content(dict(blob))

        return jsonify({
            'blob_hash': blob['blob_hash'],
            'content': content,
            'content_type': blob['content_type'],
            'created_at': str(blob['created_at']) if blob['created_at'] else None,
            'byte_size': blob['byte_size'],
            'encrypted': bool(blob.get('content_encrypted'))
        })

    elif commit_hash:
        cur.execute(
            '''SELECT c.*, b.content, b.content_type, b.content_encrypted, b.nonce, b.encryption_key_id
               FROM commits c
               JOIN tree_entries t ON c.tree_hash = t.tree_hash AND c.tenant_id = t.tenant_id
               JOIN blobs b ON t.blob_hash = b.blob_hash AND t.tenant_id = b.tenant_id
               WHERE c.commit_hash = %s AND c.tenant_id = %s''',
            (commit_hash, DEFAULT_TENANT)
        )
        commit = cur.fetchone()
        cur.close()
        if not commit:
            return jsonify({'error': 'Commit not found'}), 404
        result = dict(commit)

        # Decrypt content if needed
        result['content'] = decrypt_blob_content(result)
        result['encrypted'] = bool(result.get('content_encrypted'))

        # Clean up encryption fields from response
        result.pop('content_encrypted', None)
        result.pop('nonce', None)
        result.pop('encryption_key_id', None)

        if result.get('created_at'):
            result['created_at'] = str(result['created_at'])
        return jsonify(result)

    return jsonify({'error': 'Hash or commit required'}), 400

@app.route('/v2/quick-brief', methods=['GET'])
def quick_brief():
    """Get a context brief for current state."""
    branch = request.args.get('branch', 'command-center')

    cur = get_cursor()
    cur.execute('SELECT * FROM branches WHERE name = %s AND tenant_id = %s', (branch, DEFAULT_TENANT))
    branch_info = cur.fetchone()

    if not branch_info:
        cur.close()
        return jsonify({'error': f'Branch {branch} not found'}), 404

    cur.execute(
        '''SELECT commit_hash, message, created_at, author
           FROM commits WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 5''',
        (DEFAULT_TENANT,)
    )
    recent_commits = []
    for row in cur.fetchall():
        r = dict(row)
        if r.get('created_at'):
            r['created_at'] = str(r['created_at'])
        recent_commits.append(r)

    cur.execute(
        '''SELECT session_id, branch, summary, synced_at
           FROM sessions WHERE tenant_id = %s ORDER BY synced_at DESC LIMIT 5''',
        (DEFAULT_TENANT,)
    )
    pending_sessions = []
    for row in cur.fetchall():
        r = dict(row)
        if r.get('synced_at'):
            r['synced_at'] = str(r['synced_at'])
        pending_sessions.append(r)

    cur.execute('SELECT name FROM branches WHERE tenant_id = %s', (DEFAULT_TENANT,))
    branches = [dict(row) for row in cur.fetchall()]

    cur.close()
    return jsonify({
        'current_branch': branch,
        'head_commit': branch_info['head_commit'],
        'recent_commits': recent_commits,
        'pending_sessions': pending_sessions,
        'branches': branches,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

# ==================== CROSS-REFERENCES ====================

@app.route('/v2/link', methods=['POST'])
def create_link():
    """Create a resonance link between two memories."""
    data = request.get_json() or {}
    source_blob = data.get('source_blob')
    target_blob = data.get('target_blob')
    source_branch = data.get('source_branch')
    target_branch = data.get('target_branch')
    link_type = data.get('link_type', 'resonance')
    weight = data.get('weight', 1.0)
    reasoning = data.get('reasoning', '')

    if not all([source_blob, target_blob, source_branch, target_branch]):
        return jsonify({'error': 'source_blob, target_blob, source_branch, target_branch required'}), 400

    valid_types = ['resonance', 'causal', 'contradiction', 'elaboration', 'application']
    if link_type not in valid_types:
        return jsonify({'error': f'Invalid link_type. Must be one of: {valid_types}'}), 400

    db = get_db()
    cur = get_cursor()
    now = datetime.utcnow().isoformat() + 'Z'

    try:
        cur.execute(
            '''INSERT INTO cross_references
               (tenant_id, source_blob, target_blob, source_branch, target_branch,
                link_type, weight, reasoning, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (DEFAULT_TENANT, source_blob, target_blob, source_branch, target_branch,
             link_type, weight, reasoning, now)
        )
        db.commit()
        cur.close()

        return jsonify({
            'status': 'linked',
            'source_blob': source_blob,
            'target_blob': target_blob,
            'link_type': link_type,
            'created_at': now
        }), 201

    except psycopg2.IntegrityError as e:
        db.rollback()
        cur.close()
        if 'unique' in str(e).lower():
            return jsonify({'error': 'Link already exists between these blobs'}), 409
        return jsonify({'error': str(e)}), 400

@app.route('/v2/links', methods=['GET'])
def list_links():
    """List cross-references with optional filtering."""
    blob = request.args.get('blob')
    branch = request.args.get('branch')
    link_type = request.args.get('type')
    limit = request.args.get('limit', 50, type=int)

    cur = get_cursor()

    sql = 'SELECT * FROM cross_references WHERE tenant_id = %s'
    params = [DEFAULT_TENANT]

    if blob:
        sql += ' AND (source_blob = %s OR target_blob = %s)'
        params.extend([blob, blob])

    if branch:
        sql += ' AND (source_branch = %s OR target_branch = %s)'
        params.extend([branch, branch])

    if link_type:
        sql += ' AND link_type = %s'
        params.append(link_type)

    sql += ' ORDER BY created_at DESC LIMIT %s'
    params.append(limit)

    cur.execute(sql, params)
    links = []
    for row in cur.fetchall():
        r = dict(row)
        if r.get('created_at'):
            r['created_at'] = str(r['created_at'])
        links.append(r)

    cur.close()
    return jsonify({'links': links, 'count': len(links)})

@app.route('/v2/graph', methods=['GET'])
def get_graph():
    """Get graph representation for visualization."""
    branch = request.args.get('branch')
    limit = request.args.get('limit', 100, type=int)

    cur = get_cursor()

    if branch:
        nodes_sql = '''
            SELECT DISTINCT b.blob_hash, b.content_type, b.created_at,
                   substring(b.content, 1, 200) as preview
            FROM blobs b
            JOIN tree_entries t ON b.blob_hash = t.blob_hash AND b.tenant_id = t.tenant_id
            JOIN commits c ON t.tree_hash = c.tree_hash AND t.tenant_id = c.tenant_id
            JOIN branches br ON (c.commit_hash = br.head_commit OR c.parent_hash IS NOT NULL) AND br.tenant_id = c.tenant_id
            WHERE br.name = %s AND b.tenant_id = %s
            LIMIT %s
        '''
        cur.execute(nodes_sql, (branch, DEFAULT_TENANT, limit))
    else:
        nodes_sql = '''
            SELECT blob_hash, content_type, created_at,
                   substring(content, 1, 200) as preview
            FROM blobs WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s
        '''
        cur.execute(nodes_sql, (DEFAULT_TENANT, limit))

    nodes = []
    for row in cur.fetchall():
        nodes.append({
            'id': row['blob_hash'],
            'type': row['content_type'],
            'created_at': str(row['created_at']) if row['created_at'] else None,
            'preview': row['preview']
        })

    if branch:
        edges_sql = '''
            SELECT * FROM cross_references
            WHERE (source_branch = %s OR target_branch = %s) AND tenant_id = %s LIMIT %s
        '''
        cur.execute(edges_sql, (branch, branch, DEFAULT_TENANT, limit))
    else:
        edges_sql = 'SELECT * FROM cross_references WHERE tenant_id = %s LIMIT %s'
        cur.execute(edges_sql, (DEFAULT_TENANT, limit))

    edges = []
    for row in cur.fetchall():
        edges.append({
            'source': row['source_blob'],
            'target': row['target_blob'],
            'type': row['link_type'],
            'weight': row['weight'],
            'reasoning': row['reasoning']
        })

    cur.close()
    return jsonify({
        'nodes': nodes,
        'edges': edges,
        'node_count': len(nodes),
        'edge_count': len(edges)
    })

@app.route('/v2/reflect', methods=['GET'])
def reflect():
    """Surface latent insights by cross-branch link density."""
    min_links = request.args.get('min_links', 2, type=int)
    limit = request.args.get('limit', 20, type=int)

    cur = get_cursor()

    # Postgres version with subquery
    sql = '''
        SELECT b.blob_hash, b.content_type, substring(b.content, 1, 500) as preview,
               (SELECT COUNT(*) FROM cross_references cr
                WHERE (cr.source_blob = b.blob_hash OR cr.target_blob = b.blob_hash)
                AND cr.tenant_id = %s) as link_count
        FROM blobs b
        WHERE b.tenant_id = %s
        HAVING (SELECT COUNT(*) FROM cross_references cr
                WHERE (cr.source_blob = b.blob_hash OR cr.target_blob = b.blob_hash)
                AND cr.tenant_id = %s) >= %s
        ORDER BY link_count DESC
        LIMIT %s
    '''

    cur.execute(sql, (DEFAULT_TENANT, DEFAULT_TENANT, DEFAULT_TENANT, min_links, limit))
    insights = []

    for row in cur.fetchall():
        insights.append({
            'blob_hash': row['blob_hash'],
            'link_count': row['link_count'],
            'content_type': row['content_type'],
            'preview': row['preview']
        })

    cross_branch_sql = '''
        SELECT cr.*,
               substring(b1.content, 1, 200) as source_preview,
               substring(b2.content, 1, 200) as target_preview
        FROM cross_references cr
        JOIN blobs b1 ON cr.source_blob = b1.blob_hash AND cr.tenant_id = b1.tenant_id
        JOIN blobs b2 ON cr.target_blob = b2.blob_hash AND cr.tenant_id = b2.tenant_id
        WHERE cr.source_branch != cr.target_branch AND cr.tenant_id = %s
        ORDER BY cr.weight DESC, cr.created_at DESC
        LIMIT %s
    '''
    cur.execute(cross_branch_sql, (DEFAULT_TENANT, limit))
    cross_branch_links = []
    for row in cur.fetchall():
        r = dict(row)
        if r.get('created_at'):
            r['created_at'] = str(r['created_at'])
        cross_branch_links.append(r)

    cur.close()
    return jsonify({
        'highly_connected': insights,
        'cross_branch_links': cross_branch_links,
        'insight': 'Memories with high link counts represent conceptual hubs. Cross-branch links reveal how ideas flow between cognitive domains.',
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

# ==================== SESSIONS ====================

@app.route('/v2/sync', methods=['POST'])
def sync_session():
    """Session sync from Command Center (v1 compatible)."""
    data = request.get_json() or {}
    session_id = data.get('session_id')
    project = data.get('project', 'command-center')
    content = data.get('content', {})
    summary = data.get('summary', '')

    if not session_id:
        return jsonify({'error': 'Session ID required'}), 400

    db = get_db()
    cur = get_cursor()
    now = datetime.utcnow().isoformat() + 'Z'
    branch = get_branch_for_project(project)
    content_str = json.dumps(content) if isinstance(content, dict) else str(content)

    # Upsert session
    cur.execute(
        '''INSERT INTO sessions (session_id, tenant_id, branch, content, summary, synced_at, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (session_id) DO UPDATE SET
               content = EXCLUDED.content,
               summary = EXCLUDED.summary,
               synced_at = EXCLUDED.synced_at,
               status = EXCLUDED.status''',
        (session_id, DEFAULT_TENANT, branch, content_str, summary, now, 'synced')
    )
    db.commit()
    cur.close()

    return jsonify({
        'status': 'synced',
        'session_id': session_id,
        'branch': branch,
        'synced_at': now
    })

@app.route('/v2/sessions', methods=['GET'])
def list_sessions():
    """List synced sessions."""
    branch = request.args.get('branch')
    status = request.args.get('status')
    limit = request.args.get('limit', 20, type=int)

    cur = get_cursor()

    sql = 'SELECT * FROM sessions WHERE tenant_id = %s'
    params = [DEFAULT_TENANT]

    if branch:
        sql += ' AND branch = %s'
        params.append(branch)

    if status:
        sql += ' AND status = %s'
        params.append(status)

    sql += ' ORDER BY synced_at DESC LIMIT %s'
    params.append(limit)

    cur.execute(sql, params)
    sessions = []
    for row in cur.fetchall():
        r = dict(row)
        if r.get('synced_at'):
            r['synced_at'] = str(r['synced_at'])
        sessions.append(r)

    cur.close()
    return jsonify({'sessions': sessions, 'count': len(sessions)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
