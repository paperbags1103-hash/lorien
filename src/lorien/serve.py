"""lorien serve — local knowledge graph web viewer."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .schema import GraphStore

_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>lorien — knowledge graph</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d1117;color:#e6edf3;display:flex;height:100vh;overflow:hidden}
#sidebar{width:320px;min-width:220px;background:#161b22;border-right:1px solid #30363d;display:flex;flex-direction:column;padding:0}
#sidebar h1{font-size:14px;font-weight:700;padding:16px;border-bottom:1px solid #30363d;color:#58a6ff;letter-spacing:.05em}
#search{padding:10px 12px;border-bottom:1px solid #30363d}
#search input{width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;padding:6px 10px;font-size:13px;outline:none}
#search input:focus{border-color:#58a6ff}
#panel{flex:1;overflow-y:auto;padding:12px}
#panel h2{font-size:12px;font-weight:600;color:#8b949e;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}
.fact-item{font-size:12px;padding:6px 8px;margin:3px 0;background:#0d1117;border-radius:4px;border-left:2px solid #58a6ff;color:#c9d1d9;line-height:1.4}
.rule-item{font-size:12px;padding:6px 8px;margin:3px 0;background:#0d1117;border-radius:4px;border-left:2px solid #f78166;color:#c9d1d9;line-height:1.4}
.rule-priority{font-size:10px;color:#8b949e;margin-left:4px}
#stats{padding:10px 12px;border-top:1px solid #30363d;font-size:11px;color:#8b949e}
#graph{flex:1;position:relative}
#loading{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:14px;color:#8b949e;background:#0d1117}
</style>
</head>
<body>
<div id="sidebar">
  <h1>🌳 lorien</h1>
  <div id="search"><input id="q" placeholder="엔티티 검색…" autocomplete="off"/></div>
  <div id="panel"><p style="font-size:12px;color:#8b949e">노드를 클릭하면 상세 정보가 표시됩니다.</p></div>
  <div id="stats" id="stats">로딩 중…</div>
</div>
<div id="graph">
  <div id="loading">그래프 로딩 중…</div>
</div>

<script>
let allData = null;
let network = null;

async function loadGraph() {
  const res = await fetch('/api/graph');
  allData = await res.json();
  renderGraph(allData);
  document.getElementById('loading').style.display = 'none';
  document.getElementById('stats').textContent =
    `Entity ${allData.stats.entities} · Fact ${allData.stats.facts} · Rule ${allData.stats.rules}`;
}

function renderGraph(data) {
  const typeColor = {
    person: '#f78166', project: '#79c0ff', tool: '#56d364',
    concept: '#d2a8ff', org: '#ffa657', place: '#e3b341',
  };
  const nodes = new vis.DataSet(data.nodes.map(n => ({
    id: n.id, label: n.name,
    color: { background: typeColor[n.entity_type] || '#8b949e', border: '#30363d', highlight: {background:'#fff',border:'#58a6ff'} },
    font: { color: '#e6edf3', size: 13 },
    shape: 'dot', size: 14 + Math.min(n.fact_count * 2, 20),
    title: `${n.entity_type} · ${n.fact_count} facts · ${n.rule_count} rules`
  })));
  const edges = new vis.DataSet(data.edges.map(e => ({
    from: e.from, to: e.to,
    label: e.relation || '', font: { size: 10, color: '#8b949e' },
    color: { color: '#30363d', highlight: '#58a6ff' },
    arrows: 'to', smooth: { type: 'curvedCW', roundness: 0.2 }
  })));

  const container = document.getElementById('graph');
  network = new vis.Network(container, { nodes, edges }, {
    physics: { stabilization: { iterations: 150 }, barnesHut: { gravitationalConstant: -8000, springLength: 120 } },
    interaction: { hover: true, tooltipDelay: 200 },
  });
  network.on('click', async params => {
    if (params.nodes.length) showEntity(params.nodes[0]);
  });
}

async function showEntity(id) {
  const res = await fetch(`/api/entity/${id}`);
  const d = await res.json();
  const panel = document.getElementById('panel');
  const facts = (d.facts||[]).map(f =>
    `<div class="fact-item">${esc(f.text)}</div>`).join('');
  const rules = (d.rules||[]).map(r =>
    `<div class="rule-item">${esc(r.text)}<span class="rule-priority">p${r.priority}</span></div>`).join('');
  panel.innerHTML = `
    <h2>${esc(d.name)} <span style="color:#8b949e;font-weight:400">${d.entity_type}</span></h2>
    <br/>
    ${facts ? '<h2>Facts</h2>' + facts : ''}
    ${rules ? '<br/><h2>Rules</h2>' + rules : ''}
    ${!facts && !rules ? '<p style="font-size:12px;color:#8b949e">연결된 데이터 없음</p>' : ''}
  `;
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

document.getElementById('q').addEventListener('input', e => {
  const q = e.target.value.toLowerCase().trim();
  if (!allData || !network) return;
  if (!q) { network.selectNodes([]); return; }
  const match = allData.nodes.filter(n => n.name.toLowerCase().includes(q)).map(n => n.id);
  network.selectNodes(match);
  if (match.length === 1) { network.focus(match[0], { scale: 1.5, animation: true }); }
});

loadGraph();
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    store: GraphStore

    def log_message(self, fmt: str, *args: object) -> None:  # silence default logs
        pass

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "":
            self._send(200, "text/html", _HTML.encode())
        elif path == "/api/graph":
            self._send(200, "application/json", self._graph_json())
        elif path.startswith("/api/entity/"):
            entity_id = path[len("/api/entity/"):]
            self._send(200, "application/json", self._entity_json(entity_id))
        else:
            self._send(404, "text/plain", b"Not found")

    def _graph_json(self) -> bytes:
        store = self.__class__.store
        nodes = []
        edges = []

        # Entities with fact/rule counts
        rows = store.query(
            "MATCH (e:Entity) RETURN e.id, e.name, e.entity_type, e.status"
        )
        entity_ids = set()
        for row in rows:
            eid, name, etype, status = row
            if status != "active":
                continue
            entity_ids.add(eid)
            # count facts
            fc = list(store.query(f"MATCH (f:Fact)-[:ABOUT]->(e:Entity {{id:'{eid}'}}) RETURN count(f)"))
            rc = list(store.query(f"MATCH (e:Entity {{id:'{eid}'}})-[:HAS_RULE]->(r:Rule) RETURN count(r)"))
            nodes.append({
                "id": eid, "name": name, "entity_type": etype,
                "fact_count": fc[0][0] if fc else 0,
                "rule_count": rc[0][0] if rc else 0,
            })

        # RELATED_TO edges
        rel_rows = store.query(
            "MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity) RETURN a.id, b.id, r.relation"
        )
        for row in rel_rows:
            src, tgt, rel = row
            if src in entity_ids and tgt in entity_ids:
                edges.append({"from": src, "to": tgt, "relation": rel or ""})

        stats_raw = store.count_nodes()
        stats = {"entities": stats_raw.get("Entity", 0),
                 "facts": stats_raw.get("Fact", 0),
                 "rules": stats_raw.get("Rule", 0)}

        return json.dumps({"nodes": nodes, "edges": edges, "stats": stats},
                          ensure_ascii=False).encode()

    def _entity_json(self, entity_id: str) -> bytes:
        store = self.__class__.store
        safe_id = entity_id.replace("'", "\\'")

        # Entity info
        rows = list(store.query(
            f"MATCH (e:Entity {{id:'{safe_id}'}}) RETURN e.name, e.entity_type"
        ))
        if not rows:
            return json.dumps({"error": "not found"}).encode()
        name, etype = rows[0]

        # Facts
        fact_rows = store.query(
            f"MATCH (f:Fact)-[:ABOUT]->(e:Entity {{id:'{safe_id}'}}) "
            f"RETURN f.text, f.confidence ORDER BY f.confidence DESC LIMIT 30"
        )
        facts = [{"text": r[0], "confidence": r[1]} for r in fact_rows]

        # Rules
        rule_rows = store.query(
            f"MATCH (e:Entity {{id:'{safe_id}'}})-[:HAS_RULE]->(r:Rule) "
            f"RETURN r.text, r.priority ORDER BY r.priority DESC"
        )
        rules = [{"text": r[0], "priority": r[1]} for r in rule_rows]

        return json.dumps(
            {"id": entity_id, "name": name, "entity_type": etype,
             "facts": facts, "rules": rules},
            ensure_ascii=False
        ).encode()

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(db_path: str = "~/.lorien/db", port: int = 7331) -> None:
    store = GraphStore(db_path=db_path)
    _Handler.store = store

    print(f"🌳 lorien serve → http://127.0.0.1:{port}")
    print("   Ctrl+C to stop")
    httpd = HTTPServer(("127.0.0.1", port), _Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ stopped")
