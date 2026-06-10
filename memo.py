#!/usr/bin/env python3
"""
memo —— 跨 AI 工具共享记忆的极简 MCP server（单文件，零依赖，仅需 Python 3）

v0.2：记忆从「清单」升级为「图」——节点 + 关联，支持联想检索与剪枝。
- remember：仅在用户明确说「记住」时存入（人工闸门），可顺带关联旧节点
- recall：联想式检索，命中节点会带出其关联节点
- link / forget：人工指挥下的连线与剪枝
- python3 memo.py map：生成单文件 HTML 脑图（只读透视，剪枝回对话里说）

存储：~/.ai-memory/memory.json（nodes + edges，纯文本可直接编辑，可 git 同步）
旧版 memories.jsonl 首次运行时自动迁移（原文件保留不动）。
可用环境变量 MEMO_DIR 改存储目录。

一键部署（注册两个 CLI + 写入指令规则 + 打通 skill 目录）：
  python3 memo.py install

手动注册（不用 install 时；绝对路径；Windows 把 python3 换成 python）：
  claude mcp add memo --scope user -- python3 /你的路径/memo.py
  codex  mcp add memo -- python3 /你的路径/memo.py
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser

DATA_DIR = os.path.expanduser(os.environ.get("MEMO_DIR", "~/.ai-memory"))
DATA_FILE = os.path.join(DATA_DIR, "memory.json")
LEGACY_FILE = os.path.join(DATA_DIR, "memories.jsonl")

# ---------------- 存储层：一个 JSON 文件（nodes + edges） ----------------

def _load_db():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    db = {"seq": 0, "nodes": [], "edges": []}
    if os.path.exists(LEGACY_FILE):  # 迁移 v0.1 的 jsonl
        with open(LEGACY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    it = json.loads(line)
                except json.JSONDecodeError:
                    continue
                db["seq"] += 1
                db["nodes"].append({
                    "id": db["seq"],
                    "time": it.get("time", ""),
                    "tags": it.get("tags", ""),
                    "text": it.get("text", ""),
                })
        _save_db(db)
    return db


def _save_db(db):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA_FILE)


def _node(db, nid):
    for n in db["nodes"]:
        if n["id"] == nid:
            return n
    return None


def _neighbors(db, nid):
    out = []
    for e in db["edges"]:
        if e["a"] == nid:
            other = e["b"]
        elif e["b"] == nid:
            other = e["a"]
        else:
            continue
        n = _node(db, other)
        if n:
            out.append((e.get("rel", "相关"), n))
    return out


def _fmt(n):
    tags = " [{}]".format(n["tags"]) if n.get("tags") else ""
    return "#{} ({}{}) {}".format(n["id"], n.get("time", "?"), tags, n.get("text", ""))


def _parse_ids(v):
    """接受 3 / "3" / "#3" / "3 5 7" / [3, 5] 等各种写法。"""
    raw = v if isinstance(v, list) else str(v).replace(",", " ").split()
    ids = []
    for r in raw:
        try:
            ids.append(int(str(r).strip().lstrip("#")))
        except ValueError:
            pass
    return ids

# ---------------- 五个工具 ----------------

def tool_remember(content="", tags="", link_to=None, **_):
    content = str(content or "").strip()
    if not content:
        return "内容为空，未保存。"
    db = _load_db()
    db["seq"] += 1
    nid = db["seq"]
    db["nodes"].append({
        "id": nid,
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "tags": str(tags or "").strip(),
        "text": content,
    })
    linked = []
    if link_to is not None:
        for t in _parse_ids(link_to):
            if t != nid and _node(db, t):
                db["edges"].append({"a": nid, "b": t, "rel": "相关"})
                linked.append("#{}".format(t))
    _save_db(db)
    msg = "已存为 #{}（库内共 {} 条）".format(nid, len(db["nodes"]))
    if linked:
        msg += "，并关联到 " + "、".join(linked)
    return msg + "。"


def tool_recall(query="", limit=5, **_):
    db = _load_db()
    if not db["nodes"]:
        return "记忆库还是空的。"
    tokens = [t for t in str(query or "").lower().split() if t]
    if not tokens:
        return tool_recent(limit)
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 5
    scored = []
    for n in db["nodes"]:
        hay = (str(n.get("text", "")) + " " + str(n.get("tags", ""))).lower()
        s = sum(hay.count(t) for t in tokens)
        if s > 0:
            scored.append((s, n["id"], n))
    if not scored:
        return "没有找到与「{}」相关的记忆。可换关键词，或用 recent 看最近条目。".format(query)
    scored.sort(key=lambda x: (-x[0], -x[1]))  # 相关度优先，其次取较新的
    hits = [n for _s, _i, n in scored[:limit]]
    hit_ids = {n["id"] for n in hits}
    lines = []
    for n in hits:
        lines.append(_fmt(n))
        nb = [x for x in _neighbors(db, n["id"]) if x[1]["id"] not in hit_ids][:3]
        for rel, m in nb:
            lines.append("   └ 关联（{}）{}".format(rel, _fmt(m)))
    return "找到 {} 条相关记忆（含其关联节点）：\n{}".format(len(scored), "\n".join(lines))


def tool_link(a=None, b=None, rel="相关", **_):
    db = _load_db()
    ia, ib = _parse_ids(a), _parse_ids(b)
    if not ia or not ib:
        return "需要提供两个节点编号，如 a=3 b=7。"
    na, nb = _node(db, ia[0]), _node(db, ib[0])
    if not na or not nb:
        return "编号不存在，请先用 recall / recent 确认编号。"
    rel = str(rel or "相关").strip() or "相关"
    for e in db["edges"]:
        if {e["a"], e["b"]} == {na["id"], nb["id"]}:
            e["rel"] = rel
            _save_db(db)
            return "#{} 与 #{} 已有关联，关系更新为「{}」。".format(na["id"], nb["id"], rel)
    db["edges"].append({"a": na["id"], "b": nb["id"], "rel": rel})
    _save_db(db)
    return "已关联：#{} —{}— #{}。".format(na["id"], rel, nb["id"])


def tool_forget(ids=None, **_):
    db = _load_db()
    targets = [i for i in _parse_ids(ids) if _node(db, i)]
    if not targets:
        return "没有找到要删除的编号，请先用 recall / recent 确认。"
    tset = set(targets)
    db["nodes"] = [n for n in db["nodes"] if n["id"] not in tset]
    before = len(db["edges"])
    db["edges"] = [e for e in db["edges"] if e["a"] not in tset and e["b"] not in tset]
    _save_db(db)
    return "已剪掉 {} 个节点（{}）及其 {} 条关联。".format(
        len(targets), "、".join("#{}".format(i) for i in targets), before - len(db["edges"]))


def tool_recent(n=5, **_):
    db = _load_db()
    if not db["nodes"]:
        return "记忆库还是空的。"
    try:
        n = max(1, int(n))
    except (TypeError, ValueError):
        n = 5
    lines = [_fmt(x) for x in db["nodes"][-n:]]
    return "最近 {} 条：\n{}".format(len(lines), "\n".join(lines))


def tool_dump(tag="", **_):
    db = _load_db()
    if not db["nodes"]:
        return "记忆库还是空的。"
    tag = str(tag or "").strip().lower()
    nodes = [n for n in db["nodes"] if not tag or tag in str(n.get("tags", "")).lower()]
    if not nodes:
        return "没有 tag 含「{}」的记忆。".format(tag)
    ids = {n["id"] for n in nodes}
    out = ["共 {} 条记忆：".format(len(nodes))] + [_fmt(n) for n in nodes]
    rels = ["#{} —{}— #{}".format(e["a"], e.get("rel", "相关"), e["b"])
            for e in db["edges"] if e["a"] in ids or e["b"] in ids]
    if rels:
        out.append("关联：")
        out.extend(rels)
    return "\n".join(out)


TOOLS = [
    {
        "name": "remember",
        "description": (
            "两种情况下调用：① 用户明确说「记住：…」「别忘了…」；"
            "② 你按规则提议存档、用户当场明确同意之后。未经用户确认绝不写入。"
            "把用户指定或确认的内容存为记忆节点（Claude Code / Codex 等共用同一个库），"
            "精炼成一两句话，tags 带项目名；若与某条旧记忆有关，用 link_to 填编号。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容，精炼的一两句话"},
                "tags": {"type": "string", "description": "标签（含项目名），空格分隔"},
                "link_to": {"type": "string", "description": "可选：要关联的旧节点编号，如 \"3\" 或 \"3 7\""},
            },
            "required": ["content"],
        },
    },
    {
        "name": "recall",
        "description": (
            "联想式检索共享记忆库：按关键词命中节点，并带出每个命中节点的关联节点（最多 3 个）。"
            "任务有延续性、或用户提到「之前 / 上次 / 继续」时先调用。"
            "关键词空格分隔且包含项目名，中文建议拆成短词。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词，空格分隔，如：lovart 成本"},
                "limit": {"type": "integer", "description": "最多返回几条，默认 5"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "link",
        "description": (
            "仅在用户明确指出两条记忆相关时调用，在 #a 与 #b 之间建立关联；"
            "rel 用一两个词描述关系（如：相关、取代、属于、并行方案）。不要主动连线。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "节点编号"},
                "b": {"type": "string", "description": "节点编号"},
                "rel": {"type": "string", "description": "关系描述，默认「相关」"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "forget",
        "description": (
            "剪枝：仅在用户要求忘掉 / 删除 / 作废某些记忆时调用，"
            "按编号删除节点及其所有关联。编号可从 recall / recent 的结果里取。不要主动删除。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ids": {"type": "string", "description": "要删除的编号，可多个，如 \"5\" 或 \"5 7 12\""},
            },
            "required": ["ids"],
        },
    },
    {
        "name": "recent",
        "description": "查看最近的 n 条记忆节点（含编号），了解各工具里最新发生了什么。",
        "inputSchema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "description": "条数，默认 5"}},
        },
    },
    {
        "name": "dump",
        "description": (
            "导出某个 tag 下的全部记忆及其关联，专供「沉淀成 skill」或整体回顾使用。"
            "仅在用户明确说「沉淀 / 导出 / 全量回顾」时调用——日常检索一律用 recall，"
            "因为 dump 会一次性占用大量上下文。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "要导出的 tag（如项目名）；留空导出全部"},
            },
        },
    },
]

HANDLERS = {
    "remember": tool_remember,
    "recall": tool_recall,
    "link": tool_link,
    "forget": tool_forget,
    "recent": tool_recent,
    "dump": tool_dump,
}

# ---------------- 脑图：python3 memo.py map ----------------

MAP_TEMPLATE = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>memo 记忆脑图</title>
<style>
body{margin:0;display:flex;height:100vh;background:#faf9f5;color:#2c2c2a;
 font:14px/1.6 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
#c{flex:1;height:100vh;cursor:grab}
#side{width:320px;border-left:1px solid #e3e1d9;background:#fff;padding:18px;overflow:auto;box-sizing:border-box}
h3{margin:0 0 6px;font-size:16px}
.muted{color:#8a887f;font-size:12px}
.tag{display:inline-block;background:#eeedfe;color:#3c3489;border-radius:10px;padding:1px 9px;font-size:12px;margin:8px 4px 0 0}
#info{margin-top:14px;padding-top:12px;border-top:1px solid #eeece4}
.t{font-size:14px;white-space:pre-wrap}
.kbd{background:#f1efe8;border-radius:4px;padding:0 5px;font-family:ui-monospace,monospace;font-size:12px}
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="side">
 <h3>memo 记忆脑图</h3>
 <div class="muted">节点颜色 = 第一个 tag；连线 = 关联。<br>拖动节点整理布局，空白处拖动平移，点击节点看详情。<br>这是只读透视片——剪枝请回到对话里说「忘掉 #编号」。</div>
 <div id="info"><div class="muted" style="margin-top:14px">尚未选中节点</div></div>
</div>
<script>
const DATA = __DATA__;
const cv = document.getElementById('c'), info = document.getElementById('info');
const PAL = ['#534AB7','#0F6E56','#993C1D','#993556','#185FA5','#3B6D11','#854F0B','#5F5E5A'];
function colorOf(tags){
  const t = (tags||'').split(/\s+/)[0] || '';
  let h = 0; for (const ch of t) h = (h*31 + ch.charCodeAt(0)) >>> 0;
  return t ? PAL[h % PAL.length] : '#5F5E5A';
}
const deg = {};
DATA.edges.forEach(e => { deg[e.a]=(deg[e.a]||0)+1; deg[e.b]=(deg[e.b]||0)+1; });
const N = DATA.nodes.map((n,i) => ({...n,
  x: Math.cos(i*2.4)*60*Math.sqrt(i+1), y: Math.sin(i*2.4)*60*Math.sqrt(i+1),
  vx:0, vy:0, d:(deg[n.id]||0), c:colorOf(n.tags)}));
const byId = {}; N.forEach(n => byId[n.id]=n);
const E = DATA.edges.filter(e => byId[e.a] && byId[e.b]);
let W, H, ctx = cv.getContext('2d'), sel=null, drag=null, ox=0, oy=0, px=0, py=0;
function resize(){
  W = cv.clientWidth; H = cv.clientHeight;
  const r = devicePixelRatio || 1;
  cv.width = W*r; cv.height = H*r; ctx.setTransform(r,0,0,r,0,0);
}
window.addEventListener('resize', resize);
function tick(){
  for (let i=0;i<N.length;i++) for (let j=i+1;j<N.length;j++){
    const a=N[i], b=N[j];
    let dx=a.x-b.x, dy=a.y-b.y, d2=dx*dx+dy*dy+0.01, d=Math.sqrt(d2);
    const f = 1800/d2; dx/=d; dy/=d;
    a.vx+=dx*f; a.vy+=dy*f; b.vx-=dx*f; b.vy-=dy*f;
  }
  E.forEach(e => { const a=byId[e.a], b=byId[e.b];
    let dx=b.x-a.x, dy=b.y-a.y, d=Math.sqrt(dx*dx+dy*dy)+0.01;
    const f=(d-130)*0.02; dx/=d; dy/=d;
    a.vx+=dx*f; a.vy+=dy*f; b.vx-=dx*f; b.vy-=dy*f; });
  N.forEach(n => { n.vx-=n.x*0.005; n.vy-=n.y*0.005;
    if (n!==drag){ n.x+=n.vx*=0.85; n.y+=n.vy*=0.85; } });
}
function draw(){
  ctx.clearRect(0,0,W,H);
  ctx.save(); ctx.translate(W/2+ox, H/2+oy);
  E.forEach(e => { const a=byId[e.a], b=byId[e.b];
    const hot = sel && (sel===a || sel===b);
    ctx.strokeStyle = hot ? '#7F77DD' : '#d8d5ca'; ctx.lineWidth = hot ? 1.6 : 1;
    ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke();
    if (e.rel && e.rel !== '相关'){
      ctx.fillStyle='#9a978c'; ctx.font='11px sans-serif'; ctx.textAlign='center';
      ctx.fillText(e.rel,(a.x+b.x)/2,(a.y+b.y)/2-4);
    }});
  N.forEach(n => { const r = 7 + Math.min(n.d*2, 9);
    ctx.beginPath(); ctx.arc(n.x,n.y,r,0,7);
    ctx.fillStyle=n.c; ctx.fill();
    if (n===sel){ ctx.lineWidth=3; ctx.strokeStyle='#2c2c2a'; ctx.stroke(); }
    ctx.fillStyle='#2c2c2a'; ctx.textAlign='left'; ctx.font='12px sans-serif';
    const t=(n.text||'');
    ctx.fillText('#'+n.id+' '+t.slice(0,12)+(t.length>12?'…':''), n.x+r+5, n.y+4);
  });
  ctx.restore();
}
function loop(){ tick(); draw(); requestAnimationFrame(loop); }
function pick(mx,my){
  const x=mx-W/2-ox, y=my-H/2-oy;
  let best=null, bd=500;
  N.forEach(n => { const dx=n.x-x, dy=n.y-y, d=dx*dx+dy*dy;
    if (d<bd){ bd=d; best=n; }});
  return best;
}
cv.addEventListener('mousedown', e => {
  const r=cv.getBoundingClientRect();
  const n=pick(e.clientX-r.left, e.clientY-r.top);
  if (n){ drag=n; sel=n; show(n); }
  else { drag='pan'; px=e.clientX; py=e.clientY; }
});
window.addEventListener('mousemove', e => {
  const r=cv.getBoundingClientRect();
  if (drag && drag!=='pan'){
    drag.x=e.clientX-r.left-W/2-ox; drag.y=e.clientY-r.top-H/2-oy; drag.vx=drag.vy=0;
  } else if (drag==='pan'){ ox+=e.clientX-px; oy+=e.clientY-py; px=e.clientX; py=e.clientY; }
});
window.addEventListener('mouseup', () => drag=null);
function esc(s){ return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function show(n){
  const tags=(n.tags||'').split(/\s+/).filter(Boolean).map(t=>'<span class="tag">'+esc(t)+'</span>').join('');
  info.innerHTML = '<div class="muted">#'+n.id+' · '+esc(n.time||'')+'</div>'
    + '<div class="t" style="margin-top:6px">'+esc(n.text||'')+'</div>'
    + (tags ? '<div>'+tags+'</div>' : '')
    + '<div class="muted" style="margin-top:12px">要剪掉它：对模型说 <span class="kbd">忘掉 #'+n.id+'</span></div>';
}
resize(); loop();
</script>
</body>
</html>
"""


def make_map():
    db = _load_db()
    data = json.dumps({"nodes": db["nodes"], "edges": db["edges"]},
                      ensure_ascii=False).replace("</", "<\\/")
    html = MAP_TEMPLATE.replace("__DATA__", data)
    out = os.path.join(DATA_DIR, "map.html")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("脑图已生成：" + out)
    try:
        webbrowser.open("file://" + out)
    except Exception:
        pass

# ---------------- 一键部署：python3 memo.py install ----------------

GLUE = """<!-- memo:begin -->
## 共享记忆（memo）
- 我明确说「记住：……」时调用 remember（一两句话，tags 带项目名）；我若提到它和某条旧记忆有关，用 link_to 填编号。
- 当我先提出疑问、随后给出明确指令，且当下没有反复更改时：在完成该任务后问我「要不要存进记忆：<拟存的一句话>」；我明确同意才 remember，拒绝或未回应则不存，同一话题本会话内不再追问。
- 除以上两种情况，绝不写入记忆库。
- 我说「#x 和 #y 有关 / 是取代关系」时，用 link 连线并写明 rel。
- 我说「忘掉 / 删掉 / 作废 #x」时，用 forget 剪枝。
- 任务有延续性时，先 recall（关键词含项目名），它带出的关联节点优先参考。
- 我说「沉淀」或「沉淀：<tag>」时：① 圈范围——给了 tag 就 dump 该 tag，没给就从我话里的关键词和 recent 推测，先报我确认；② 蒸馏并拟定分发方案：每条内容写进哪个 skill，按它的 tags 和内容关键词判断，可拆进多个、可新建，目标 skill 已存在则先读旧版；③ 把方案发我（目标 skill 清单 + 各自要写的要点），我确认或修改后才写入，未经确认不动任何 skill 文件；④ 写完列出已吸收的记忆编号，问我是否 forget。只收反复成立的做法与口径，一次性事实留在记忆库。
- 我说「提取 skill：<tag>」时，读取 ~/.claude/skills/<tag>/SKILL.md，把全文原样发给我并附上文件路径；只说「提取 skill」时，列出 ~/.claude/skills/ 下所有 skill 的名字和 description 供我挑选。
- 记忆与我当下说法冲突时，以当下为准。
<!-- memo:end -->"""


def _write_glue(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            old = f.read()
    if "<!-- memo:begin -->" in old:
        new = re.sub(r"<!-- memo:begin -->.*?<!-- memo:end -->", lambda _m: GLUE, old, flags=re.S)
        action = "更新"
    else:
        new = (old.rstrip() + "\n\n" if old.strip() else "") + GLUE + "\n"
        action = "写入"
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    return action


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return False, "未找到命令 " + cmd[0]


def install():
    me = os.path.abspath(__file__)
    py = sys.executable or "python3"
    print("部署 memo：" + me)
    low = me.lower()
    if "download" in low or "tmp" in low or "temp" in low:
        print("⚠ 当前路径像是临时目录，建议先把 memo.py 移到固定位置（如 ~/tools/）再重新运行。")
    for name, cli, extra in (("Claude Code", "claude", ["--scope", "user"]),
                             ("Codex", "codex", [])):
        if not shutil.which(cli):
            print("✗ {}：未检测到 {} 命令，跳过注册（装好后重跑 install 即可）。".format(name, cli))
            continue
        _run([cli, "mcp", "remove", "memo"])  # 幂等：先清掉旧注册，失败无所谓
        ok, msg = _run([cli, "mcp", "add", "memo"] + extra + ["--", py, me])
        if ok:
            print("✓ {}：memo 已注册".format(name))
        else:
            print("✗ {}：注册失败（{}）".format(name, msg or "原因未知"))
            print("   可手动执行：{} mcp add memo {}-- {} {}".format(
                cli, "--scope user " if extra else "", py, me))
    for label, p in (("Claude Code 全局指令", "~/.claude/CLAUDE.md"),
                     ("Codex 全局指令", "~/.codex/AGENTS.md")):
        action = _write_glue(os.path.expanduser(p))
        print("✓ {}：已{}共享记忆规则（{}）".format(label, action, p))
    cskills = os.path.expanduser("~/.claude/skills")
    xskills = os.path.expanduser("~/.codex/skills")
    os.makedirs(cskills, exist_ok=True)
    if os.path.islink(xskills) or os.path.exists(xskills):
        print("• skill 目录：~/.codex/skills 已存在，保持原样。")
    else:
        try:
            os.symlink(cskills, xskills)
            print("✓ skill 目录已打通：~/.codex/skills → ~/.claude/skills")
        except OSError:
            print("• 未能创建 symlink（Windows 需开发者模式），两边 skill 目录各自独立，不影响使用。")
    print("")
    print("完成。验证：终端跑 claude mcp list 应看到 memo；Codex 会话里输 /mcp。")
    print("日常用法：「记住：…」入库｜「沉淀：<tag>」生成 skill｜python3 memo.py map 看脑图。")

# ---------------- MCP 协议层：stdio + JSON-RPC 的手写最小实现 ----------------
# 只实现 tools 相关方法，这正是它能零依赖的原因。

def _reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    # ensure_ascii=True：输出纯 ASCII，任何终端编码下都不会乱
    sys.stdout.write(json.dumps(msg, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def main():
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    while True:
        line = stdin.readline()
        if not line:  # EOF：客户端关闭，退出
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method", "")
        id_ = req.get("id")
        if id_ is None:  # 通知（如 notifications/initialized）不需要回复
            continue
        if method == "initialize":
            client_ver = (req.get("params") or {}).get("protocolVersion", "2025-03-26")
            _reply(id_, {
                "protocolVersion": client_ver,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "memo", "version": "0.3.3"},
            })
        elif method == "tools/list":
            _reply(id_, {"tools": TOOLS})
        elif method == "tools/call":
            params = req.get("params") or {}
            fn = HANDLERS.get(params.get("name"))
            if fn is None:
                _reply(id_, error={"code": -32602, "message": "unknown tool"})
                continue
            try:
                text = fn(**(params.get("arguments") or {}))
                _reply(id_, {"content": [{"type": "text", "text": text}], "isError": False})
            except Exception as e:  # 工具内部出错也按协议返回，不让进程崩
                _reply(id_, {"content": [{"type": "text", "text": "出错：{}".format(e)}], "isError": True})
        elif method == "ping":
            _reply(id_, {})
        else:
            _reply(id_, error={"code": -32601, "message": "method not found: " + method})


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "map":
        make_map()
    elif cmd == "install":
        install()
    else:
        main()
