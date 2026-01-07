<?php
/**
 * Boswell MCP Server - PHP Implementation
 * Implements MCP protocol for Claude.ai Custom Connectors
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

// Boswell API base URL
$BOSWELL_API = 'https://stevekrontz.com/boswell/v2';

// Tool definitions
$TOOLS = [
    [
        'name' => 'boswell_brief',
        'description' => 'Get a quick context brief of current Boswell state - recent commits, pending sessions, all branches. Use this at conversation start to understand what\'s been happening.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => [
                'branch' => ['type' => 'string', 'description' => 'Branch to focus on (default: command-center)', 'default' => 'command-center']
            ]
        ]
    ],
    [
        'name' => 'boswell_branches',
        'description' => 'List all cognitive branches in Boswell. Branches are: tint-atlanta (CRM/business), iris (research/BCI), tint-empire (franchise), family (personal), command-center (infrastructure), boswell (memory system).',
        'inputSchema' => ['type' => 'object', 'properties' => new stdClass()]
    ],
    [
        'name' => 'boswell_head',
        'description' => 'Get the current HEAD commit for a specific branch.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => ['branch' => ['type' => 'string', 'description' => 'Branch name']],
            'required' => ['branch']
        ]
    ],
    [
        'name' => 'boswell_log',
        'description' => 'Get commit history for a branch. Shows what memories have been recorded.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => [
                'branch' => ['type' => 'string', 'description' => 'Branch name'],
                'limit' => ['type' => 'integer', 'description' => 'Max commits (default: 10)', 'default' => 10]
            ],
            'required' => ['branch']
        ]
    ],
    [
        'name' => 'boswell_search',
        'description' => 'Search memories across all branches by keyword. Returns matching content with commit info.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => [
                'query' => ['type' => 'string', 'description' => 'Search query'],
                'branch' => ['type' => 'string', 'description' => 'Optional: limit to branch'],
                'limit' => ['type' => 'integer', 'description' => 'Max results (default: 10)', 'default' => 10]
            ],
            'required' => ['query']
        ]
    ],
    [
        'name' => 'boswell_recall',
        'description' => 'Recall a specific memory by its blob hash or commit hash.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => [
                'hash' => ['type' => 'string', 'description' => 'Blob hash'],
                'commit' => ['type' => 'string', 'description' => 'Or commit hash']
            ]
        ]
    ],
    [
        'name' => 'boswell_links',
        'description' => 'List resonance links between memories. Shows cross-branch connections.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => [
                'branch' => ['type' => 'string', 'description' => 'Optional: filter by branch'],
                'link_type' => ['type' => 'string', 'description' => 'Optional: resonance, causal, etc.']
            ]
        ]
    ],
    [
        'name' => 'boswell_graph',
        'description' => 'Get the full memory graph - all nodes and edges.',
        'inputSchema' => ['type' => 'object', 'properties' => new stdClass()]
    ],
    [
        'name' => 'boswell_reflect',
        'description' => 'Get AI-surfaced insights - highly connected memories and patterns.',
        'inputSchema' => ['type' => 'object', 'properties' => new stdClass()]
    ],
    [
        'name' => 'boswell_commit',
        'description' => 'Commit a new memory to Boswell. Preserves important decisions and context.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => [
                'branch' => ['type' => 'string', 'description' => 'Branch to commit to'],
                'content' => ['type' => 'object', 'description' => 'Memory content as JSON'],
                'message' => ['type' => 'string', 'description' => 'Commit message'],
                'tags' => ['type' => 'array', 'items' => ['type' => 'string'], 'description' => 'Optional tags']
            ],
            'required' => ['branch', 'content', 'message']
        ]
    ],
    [
        'name' => 'boswell_link',
        'description' => 'Create a resonance link between two memories across branches.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => [
                'source_blob' => ['type' => 'string'],
                'target_blob' => ['type' => 'string'],
                'source_branch' => ['type' => 'string'],
                'target_branch' => ['type' => 'string'],
                'link_type' => ['type' => 'string', 'default' => 'resonance'],
                'reasoning' => ['type' => 'string', 'description' => 'Why connected']
            ],
            'required' => ['source_blob', 'target_blob', 'source_branch', 'target_branch', 'reasoning']
        ]
    ],
    [
        'name' => 'boswell_checkout',
        'description' => 'Switch focus to a different cognitive branch.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => ['branch' => ['type' => 'string', 'description' => 'Branch to check out']],
            'required' => ['branch']
        ]
    ]
];

function callBoswellAPI($endpoint, $method = 'GET', $params = [], $body = null) {
    global $BOSWELL_API;

    $url = $BOSWELL_API . $endpoint;
    if ($method === 'GET' && !empty($params)) {
        $url .= '?' . http_build_query($params);
    }

    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 30);

    if ($method === 'POST') {
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body));
        curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
    }

    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($httpCode >= 200 && $httpCode < 300) {
        return json_decode($response, true) ?? $response;
    }
    return ['error' => "HTTP $httpCode", 'details' => $response];
}

function executeTool($name, $args) {
    switch ($name) {
        case 'boswell_brief':
            $branch = $args['branch'] ?? 'command-center';
            return callBoswellAPI('/quick-brief', 'GET', ['branch' => $branch]);

        case 'boswell_branches':
            return callBoswellAPI('/branches');

        case 'boswell_head':
            return callBoswellAPI('/head', 'GET', ['branch' => $args['branch']]);

        case 'boswell_log':
            $params = ['branch' => $args['branch']];
            if (isset($args['limit'])) $params['limit'] = $args['limit'];
            return callBoswellAPI('/log', 'GET', $params);

        case 'boswell_search':
            $params = ['q' => $args['query']];
            if (isset($args['branch'])) $params['branch'] = $args['branch'];
            if (isset($args['limit'])) $params['limit'] = $args['limit'];
            return callBoswellAPI('/search', 'GET', $params);

        case 'boswell_recall':
            $params = [];
            if (isset($args['hash'])) $params['hash'] = $args['hash'];
            if (isset($args['commit'])) $params['commit'] = $args['commit'];
            return callBoswellAPI('/recall', 'GET', $params);

        case 'boswell_links':
            $params = [];
            if (isset($args['branch'])) $params['branch'] = $args['branch'];
            if (isset($args['link_type'])) $params['link_type'] = $args['link_type'];
            return callBoswellAPI('/links', 'GET', $params);

        case 'boswell_graph':
            return callBoswellAPI('/graph');

        case 'boswell_reflect':
            return callBoswellAPI('/reflect');

        case 'boswell_commit':
            $payload = [
                'branch' => $args['branch'],
                'content' => $args['content'],
                'message' => $args['message'],
                'author' => 'claude-web',
                'type' => 'memory'
            ];
            if (isset($args['tags'])) $payload['tags'] = $args['tags'];
            return callBoswellAPI('/commit', 'POST', [], $payload);

        case 'boswell_link':
            $payload = [
                'source_blob' => $args['source_blob'],
                'target_blob' => $args['target_blob'],
                'source_branch' => $args['source_branch'],
                'target_branch' => $args['target_branch'],
                'link_type' => $args['link_type'] ?? 'resonance',
                'reasoning' => $args['reasoning'],
                'created_by' => 'claude-web'
            ];
            return callBoswellAPI('/link', 'POST', [], $payload);

        case 'boswell_checkout':
            return callBoswellAPI('/checkout', 'POST', [], ['branch' => $args['branch']]);

        default:
            return ['error' => "Unknown tool: $name"];
    }
}

// Handle requests
if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    // Health check
    echo json_encode([
        'status' => 'ok',
        'server' => 'boswell-mcp',
        'version' => '1.0.0',
        'tools' => count($TOOLS)
    ]);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $input = file_get_contents('php://input');
    $body = json_decode($input, true);

    if (!$body) {
        http_response_code(400);
        echo json_encode(['error' => 'Invalid JSON']);
        exit;
    }

    $method = $body['method'] ?? '';
    $params = $body['params'] ?? [];
    $requestId = $body['id'] ?? null;

    $result = null;

    switch ($method) {
        case 'initialize':
            $result = [
                'protocolVersion' => '2024-11-05',
                'serverInfo' => ['name' => 'boswell-mcp', 'version' => '1.0.0'],
                'capabilities' => ['tools' => new stdClass()]
            ];
            break;

        case 'tools/list':
            $result = ['tools' => $TOOLS];
            break;

        case 'tools/call':
            $toolName = $params['name'] ?? '';
            $toolArgs = $params['arguments'] ?? [];
            $toolResult = executeTool($toolName, $toolArgs);
            $result = [
                'content' => [
                    ['type' => 'text', 'text' => json_encode($toolResult, JSON_PRETTY_PRINT)]
                ]
            ];
            break;

        case 'ping':
            $result = new stdClass();
            break;

        default:
            http_response_code(400);
            echo json_encode([
                'jsonrpc' => '2.0',
                'id' => $requestId,
                'error' => ['code' => -32601, 'message' => "Unknown method: $method"]
            ]);
            exit;
    }

    echo json_encode([
        'jsonrpc' => '2.0',
        'id' => $requestId,
        'result' => $result
    ]);
}
