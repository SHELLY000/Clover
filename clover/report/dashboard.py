"""Single-file static HTML dashboard.

No server, no external assets, no network access at render time — the
file can be dropped into a shared folder or attached to an accreditation
submission and will still render years later, which is the point.

The visual grammar is a measurement strip: each objective is drawn as a
horizontal scale from 0 to 1 with the qualifying standard as a hairline,
the bootstrap interval as a bar, and the point estimate as a tick.  A
value that is not identifiable is drawn hatched rather than solid, so the
distinction between "we measured 0.87" and "we computed 0.87 from
evidence that could not measure it" survives being looked at quickly.
"""

from __future__ import annotations

import json

from jinja2 import Template

from ..blueprint import Blueprint
from ..model import AttainmentResult, DiagnosticReport

_TEMPLATE = Template("""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ c.name }} · 课程目标达成度</title>
<style>
:root{
  --ink:#16202F; --ink-2:#42506A; --ink-3:#7A879C;
  --paper:#EEF1F6; --card:#FFFFFF; --rule:#CBD3E1;
  --pass:#0F766E; --warn:#B45309; --fail:#9F1239;
  --grid:#DDE3EE;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
 font:15px/1.6 system-ui,-apple-system,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;}
.num{font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums;}
.wrap{max-width:1080px;margin:0 auto;padding:40px 24px 72px}
header{border-bottom:2px solid var(--ink);padding-bottom:18px;margin-bottom:8px}
h1{font-size:26px;letter-spacing:-.01em;margin:0 0 6px;font-weight:650}
.sub{color:var(--ink-2);font-size:13.5px}
.sub span{margin-right:18px;white-space:nowrap}
.verdict{display:flex;gap:14px;flex-wrap:wrap;margin:22px 0 30px}
.stat{background:var(--card);border:1px solid var(--rule);border-radius:3px;
 padding:14px 18px;min-width:150px;flex:1}
.stat .k{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)}
.stat .v{font-size:27px;font-weight:600;margin-top:2px}
.stat .n{font-size:12px;color:var(--ink-2)}
h2{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3);
 margin:38px 0 12px;font-weight:600}
h2::after{content:"";display:block;height:1px;background:var(--rule);margin-top:8px}
.strip{background:var(--card);border:1px solid var(--rule);border-radius:3px;padding:6px 0}
.row{display:grid;grid-template-columns:150px 1fr 96px 44px;gap:12px;align-items:center;
 padding:11px 18px;border-bottom:1px solid var(--grid)}
.row:last-child{border-bottom:none}
.oid{font-weight:600;font-size:14px}
.oid small{display:block;font-weight:400;color:var(--ink-3);font-size:11.5px;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.scale{position:relative;height:26px;background:#F7F9FC;
 border:1px solid var(--grid);border-radius:2px;overflow:visible}
.below{position:absolute;top:0;bottom:0;left:0;background:#EDEFF4;
 border-right:1px dashed var(--ink-3)}
.bar{position:absolute;top:4px;bottom:4px;border-radius:9px;min-width:9px;
 box-shadow:0 0 0 1px rgba(22,32,47,.18)}
.bar.solid{background:var(--pass)}
.bar.hatch{background:var(--fail)}
.bar.soft{background:var(--warn)}
.tick{position:absolute;top:2px;bottom:2px;width:2px;background:var(--ink);
 border-radius:1px;z-index:2}
.std{position:absolute;top:-4px;bottom:-4px;width:1px;background:var(--ink-2);z-index:1}
.std::after{content:"合格 {{ '%.2f'|format(pol.qualifying_standard) }}";position:absolute;
 top:-15px;left:-24px;font-size:10px;color:var(--ink-2);white-space:nowrap}
.val{text-align:right;font-size:16px;font-weight:600}
.val small{display:block;font-weight:400;font-size:11px;color:var(--ink-3)}
.g{width:26px;height:26px;line-height:26px;text-align:center;border-radius:3px;
 font-weight:700;font-size:13px;color:#fff}
.gA{background:var(--pass)} .gB{background:var(--warn)} .gC{background:var(--fail)}
table{width:100%;border-collapse:collapse;background:var(--card);
 border:1px solid var(--rule);font-size:13px}
th,td{padding:8px 10px;border-bottom:1px solid var(--grid);text-align:left}
th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);
 background:#F7F9FC}
td.n,th.n{text-align:right}
.heat{width:auto;border-collapse:separate;border-spacing:2px;background:none;border:none}
.heat td{padding:0;border:none;width:44px;height:30px;text-align:center;
 border-radius:2px;font-size:11px}
.heat th{background:none;border:none;font-size:11px;padding:2px 6px}
.chk{display:flex;gap:10px;padding:10px 14px;border-left:3px solid var(--rule);
 background:var(--card);margin-bottom:6px;font-size:13.5px;align-items:flex-start}
.chk.fail{border-left-color:var(--fail)} .chk.warn{border-left-color:var(--warn)}
.chk.pass{border-left-color:var(--pass)}
.code{font-family:ui-monospace,monospace;font-size:11px;color:var(--ink-3);
 background:#F1F4F9;padding:2px 6px;border-radius:2px;white-space:nowrap}
ol.rec{background:var(--card);border:1px solid var(--rule);padding:14px 14px 14px 34px;
 margin:0;font-size:13.5px}
ol.rec li{margin:6px 0}
footer{margin-top:44px;padding-top:14px;border-top:1px solid var(--rule);
 font-size:11.5px;color:var(--ink-3);line-height:1.8}
.bands{display:flex;gap:2px;margin-top:6px}
.bands div{flex:1;text-align:center;font-size:11px;padding:5px 2px;background:#F4F6FA;
 border:1px solid var(--grid);border-radius:2px}
.bands b{display:block;font-size:14px}
@media(max-width:720px){.row{grid-template-columns:1fr;gap:6px}.scale{height:20px}}
</style></head><body><div class="wrap">

<header>
  <h1>{{ c.name }} · 课程目标达成度</h1>
  <div class="sub">
    <span>{{ c.code }}</span><span>{{ c.term }}</span>
    <span>{{ c.cohort_label or c.program }}</span>
    <span>{{ r.n_students }} 名学生</span>
    <span>{{ classes }}</span>
    <span>任课教师 {{ c.instructor }}</span>
  </div>
</header>

<div class="verdict">
  <div class="stat"><div class="k">课程达成度</div>
    <div class="v num" style="color:{{ pass_color }}">{{ '%.3f'|format(r.course_attainment) }}</div>
    <div class="n">合格标准 {{ '%.2f'|format(pol.qualifying_standard) }} · {{ verdict }}</div></div>
  <div class="stat"><div class="k">有效秩 / 目标数</div>
    <div class="v num">{{ '%.2f'|format(d.effective_rank) }} <span style="font-size:16px;color:var(--ink-3)">/ {{ d.n_objectives }}</span></div>
    <div class="n">奇异值谱熵的指数（Roy &amp; Vetterli 2007）；参与比 {{ '%.2f'|format(d.participation_ratio) }}</div></div>
  <div class="stat"><div class="k">目标区分度</div>
    <div class="v num">{{ '%.3f'|format(d.separation_index) }}</div>
    <div class="n">1 − 目标间平均 |r|</div></div>
  <div class="stat"><div class="k">不可分辨目标</div>
    <div class="v num" style="color:{{ 'var(--fail)' if n_c else 'var(--pass)' }}">{{ n_c }}</div>
    <div class="n">等级 C，共 {{ d.n_objectives }} 个目标</div></div>
</div>

<h2>课程目标达成度与可信区间</h2>
<div class="strip">
{% for o in r.objectives %}
  {% set g = d.grades.get(o.id, '?') %}
  <div class="row">
    <div class="oid">{{ o.id }} <small>指标点 {{ o.indicator }} · {{ o.target_points|round(1) }} 分</small></div>
    <div class="scale">
      <div class="below" style="width:{{ (pol.qualifying_standard*100)|round(2) }}%"></div>
      <div class="bar {{ 'hatch' if g=='C' else ('soft' if g=='B' else 'solid') }}"
           style="left:{{ (o.ci_low*100)|round(2) }}%;width:{{ ((o.ci_high-o.ci_low)*100)|round(2) }}%"></div>
      <div class="tick" style="left:{{ (o.attainment*100)|round(2) }}%"></div>
      <div class="std" style="left:{{ (pol.qualifying_standard*100)|round(2) }}%"></div>
    </div>
    <div class="val num">{{ '%.3f'|format(o.attainment) }}
      <small>[{{ '%.3f'|format(o.ci_low) }}, {{ '%.3f'|format(o.ci_high) }}]</small></div>
    <div class="g g{{ g }}" title="识别性等级 {{ g }}">{{ g }}</div>
  </div>
{% endfor %}
</div>

<h2>毕业要求指标点</h2>
<table><thead><tr><th>指标点</th><th>内容</th><th class="n">目标分值</th>
<th class="n">平均得分</th><th class="n">达成度</th></tr></thead><tbody>
{% for i in r.indicators %}
<tr><td><b>{{ i.id }}</b></td><td>{{ i.text }}</td>
<td class="n num">{{ '%.1f'|format(i.target_points) }}</td>
<td class="n num">{{ '%.2f'|format(i.mean_points) }}</td>
<td class="n num"><b>{{ '%.3f'|format(i.attainment) }}</b></td></tr>
{% endfor %}
</tbody></table>

<h2>目标间相关系数</h2>
<table class="heat"><tr><th></th>{% for oid in d.objective_ids %}<th>{{ oid }}</th>{% endfor %}</tr>
{% for i in range(d.objective_ids|length) %}
<tr><th>{{ d.objective_ids[i] }}</th>
{% for j in range(d.objective_ids|length) %}
  {% set v = d.correlation[i][j] %}
  <td style="background:{{ heat(v, i==j) }};color:{{ '#fff' if v is not none and v|abs > 0.75 else 'var(--ink)' }}">
    {{ '—' if v is none else '%.2f'|format(v) }}</td>
{% endfor %}</tr>
{% endfor %}
</table>

<h2>考核项统计</h2>
<table><thead><tr><th>考核项</th><th>类型</th><th class="n">分值</th>
<th class="n">平均比率</th><th class="n">标准差</th><th class="n">有效人数</th><th>天花板</th>
</tr></thead><tbody>
{% for it in r.items %}
<tr><td>{{ it.name }}</td><td>{{ it.kind }}</td>
<td class="n num">{{ '%.2f'|format(it.points) }}</td>
<td class="n num">{{ '%.3f'|format(it.mean_ratio) }}</td>
<td class="n num">{{ '%.2f'|format(it.sd) }}</td>
<td class="n num">{{ it.n }}</td>
<td>{{ '⚠ 是' if it.ceiling else '否' }}</td></tr>
{% endfor %}
</tbody></table>

{% if dists %}
<h2>成绩分布</h2>
{% for key, label in dists %}
{% set dd = r.distributions[key] %}
<div style="margin-bottom:14px"><b>{{ label }}</b>
  <span class="num" style="color:var(--ink-2)">　平均 {{ '%.2f'|format(dd.mean) }}　标准差 {{ '%.2f'|format(dd.sd) }}　n={{ dd.n }}</span>
  <div class="bands">
  {% for band, cnt in dd.bands.items() %}
    <div>{{ band }}<b class="num">{{ cnt }}</b>{{ '%.1f'|format(100*cnt/(dd.n or 1)) }}%</div>
  {% endfor %}
  </div></div>
{% endfor %}
{% endif %}

<h2>诊断结论 · {{ d.checks|length }} 项</h2>
{% for ck in checks_sorted %}
<div class="chk {{ ck.level }}"><span class="code">{{ ck.code }}</span>
<span>{{ ck.message }}</span></div>
{% endfor %}

{% if recs %}
<h2>持续改进建议</h2>
<ol class="rec">{% for x in recs %}<li>{{ x }}</li>{% endfor %}</ol>
{% endif %}

<footer>
  CLOVER {{ r.tool_version }} · 生成于 {{ r.generated_at }}<br>
  blueprint <span class="num">{{ r.blueprint_id }}</span> ·
  sha256 <span class="num">{{ r.blueprint_hash[:16] }}</span> ·
  cohort <span class="num">{{ r.cohort_hash[:16] }}</span><br>
  自助抽样 {{ pol.bootstrap_iterations }} 次，置信水平
  {{ '%.0f'|format(pol.bootstrap_confidence*100) }}%，随机种子 {{ pol.seed }}；
  以上全部数值均可由 <span class="num">clover verify</span> 复算校验。
</footer>
</div></body></html>""")


def _heat(v, diagonal: bool) -> str:
    if v is None:
        return "#F1F4F9"
    if diagonal:
        return "#E4E9F2"
    a = abs(float(v))
    if a >= 0.98:
        return "#9F1239"
    if a >= 0.90:
        return "#C2410C"
    if a >= 0.75:
        return "#B45309"
    if a >= 0.50:
        return "#FDE9C8"
    return "#EAF3F1"


def write_dashboard(path: str, bp: Blueprint, result: AttainmentResult,
                    report: DiagnosticReport,
                    recommendations: list[str] | None = None,
                    classes: str = "") -> str:
    order = {"fail": 0, "warn": 1, "pass": 2}
    checks_sorted = sorted(report.checks, key=lambda c: (order[c.level], c.code))
    dists = [(k, lbl) for k, lbl in (("final", "期末考核成绩"), ("total", "课程总评成绩"))
             if k in result.distributions]
    html = _TEMPLATE.render(
        c=bp.course, pol=bp.policy, r=result, d=report,
        classes=classes,
        checks_sorted=checks_sorted,
        recs=recommendations or [],
        dists=dists,
        n_c=sum(1 for g in report.grades.values() if g == "C"),
        verdict=("达成" if result.course_attainment >= bp.policy.qualifying_standard
                 else "未达成"),
        pass_color=("var(--pass)"
                    if result.course_attainment >= bp.policy.qualifying_standard
                    else "var(--fail)"),
        heat=_heat,
        json=json,
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path
