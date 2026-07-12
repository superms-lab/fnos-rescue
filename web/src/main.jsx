import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AlertTriangle, CheckCircle2, FileText, HardDrive, History, LayoutDashboard, Pause, RefreshCw, Settings, ShieldCheck, Square } from "lucide-react";
import "./style.css";

const fallbackDevices = [
  { path: "/dev/sdb", size: "4.00 TB", filesystem: "btrfs", status: "损坏（读取错误）", mountpoints: [], model: "Seagate Exos X16", serial: "DEMO-ZL27K1A3", read_only: false },
  { path: "/dev/sda", size: "2.00 TB", filesystem: "xfs", status: "正常", mountpoints: ["/mnt/data1"], model: "Sample destination", serial: "DEMO-DST01", read_only: false },
];

function Sidebar() {
  const nav = [[LayoutDashboard, "概览"], [HardDrive, "设备"], [History, "恢复任务"], [FileText, "验证报告"], [Settings, "设置"]];
  return <aside className="sidebar"><div className="brand"><ShieldCheck/><div><b>FNOS Rescue</b><small>数据恢复控制台</small></div></div><nav aria-label="主导航">{nav.map(([Icon, text], index) => <button type="button" className={index === 0 ? "active" : ""} key={text}><Icon/>{text}</button>)}</nav><p className="safety-note">只读优先<br/><span>任何源盘变更均需序列号确认</span></p></aside>;
}

function Workflow() {
  return <><section className="steps" aria-label="恢复流程">{["选择源盘", "只读保护", "选择目标", "开始恢复"].map((text, index) => <div className={index < 2 ? "done" : ""} key={text}><span>{index + 1}</span><b>{text}</b></div>)}</section><div className="warning"><AlertTriangle/>已选择疑似损坏磁盘。创建案例或读取元数据前，请先启用只读保护。</div></>;
}

function DeviceTable({ devices, selected, onSelect, onRefresh, loading }) {
  return <section className="panel devices"><h2>设备列表 <button type="button" className="refresh" onClick={onRefresh} disabled={loading}><RefreshCw className={loading ? "spin" : ""}/>{loading ? "扫描中" : "刷新"}</button></h2><div className="table-scroll"><table><thead><tr><th scope="col"><span className="sr-only">选择</span></th><th scope="col">设备</th><th scope="col">容量</th><th scope="col">文件系统</th><th scope="col">状态</th><th scope="col">挂载点</th></tr></thead><tbody>{devices.map((device, index) => <tr className={selected === index ? "selected" : ""} onClick={() => onSelect(index)} key={device.path}><td><input aria-label={`选择 ${device.path}`} type="radio" name="source" checked={selected === index} onChange={() => onSelect(index)}/></td><td><code>{device.path}</code></td><td>{device.size}</td><td>{device.filesystem || "未知"}</td><td className={device.status.includes("损坏") ? "bad" : "good"}>{device.status.includes("损坏") ? <AlertTriangle/> : <CheckCircle2/>}{device.status}</td><td>{device.mountpoints?.join(", ") || "—"}</td></tr>)}</tbody></table></div></section>;
}

function DeviceDetail({ device, onProtect, onCreateCase, live, caseInfo }) {
  if (!device) return null;
  return <section className="panel detail"><h2>设备详情</h2><dl><dt>设备路径</dt><dd><code>{device.path}</code></dd><dt>型号</dt><dd>{device.model || "未知"}</dd><dt>序列号</dt><dd>{device.serial || "不可用"}</dd><dt>容量</dt><dd>{device.size}</dd><dt>只读状态</dt><dd><span className={`badge ${device.read_only ? "safe" : "warn"}`}>{device.read_only ? "已启用" : "未启用"}</span></dd></dl><button type="button" className="primary" onClick={onProtect} disabled={!device.serial || device.read_only}><ShieldCheck/>{device.read_only ? "源盘已保护" : "启用只读保护"}</button><button type="button" onClick={onCreateCase} disabled={!live || !device.read_only || Boolean(caseInfo)}>{caseInfo ? `案例 ${caseInfo.case_id}` : "创建恢复案例"}</button><small className="disabled-hint">{!live ? "演示模式不会创建真实案例" : !device.read_only ? "只读保护后开放" : caseInfo ? "案例已安全保存" : "已满足创建条件"}</small></section>;
}

function GuidedRecovery({ device, caseInfo, destination, setDestination, onInspect, destinationInfo, onCreateJob, job, onControl, message }) {
  return <section className="panel task guided"><div className="section-heading"><div><span className="eyebrow">引导恢复</span><h2>{caseInfo ? caseInfo.case_id : "等待创建案例"}</h2></div>{job && <span className="badge safe">{job.status}</span>}</div><div className="form-grid"><label>目标目录<input value={destination} onChange={(e) => setDestination(e.target.value)} placeholder="/mnt/recovery-output"/></label><button type="button" onClick={onInspect} disabled={!caseInfo || !destination}>验证目标</button><label>恢复视图目录<input id="source-root" placeholder="/mnt/recovery-view"/></label><label>选择路径<input id="paths" placeholder="Photos/2025, Documents"/></label></div>{destinationInfo && <p className="success-line"><CheckCircle2/>目标已验证：{destinationInfo.kind} · 可用 {_formatBytes(destinationInfo.free_bytes)}</p>}<div className="job-actions"><button type="button" className="primary" onClick={onCreateJob} disabled={!destinationInfo || Boolean(job)}>创建并启动复制任务</button>{job && <><button type="button" onClick={() => onControl("pause")}><Pause/>暂停</button><button type="button" onClick={() => onControl("resume")}>继续</button><button type="button" className="danger" onClick={() => onControl("cancel")}><Square/>取消</button></>}</div>{message && <p className="form-message" role="status">{message}</p>}<small className="demo-label">任务执行沿用核心层的同盘拒绝、路径越界拒绝和逐文件 SHA-256 校验。</small></section>;
}

function _formatBytes(value) { return `${(Number(value || 0) / 1e9).toFixed(1)} GB`; }

function Summary() { return <section className="panel summary"><h2>故障摘要</h2><p className="bad">读取错误扇区 <b>25,842</b></p><p>无法读取区域 <b>3</b></p><p>文件系统损坏 <b>1</b></p><small className="demo-label">界面预览数据</small></section>; }

function ConfirmModal({ device, busy, error, onClose, onConfirm }) {
  const [serial, setSerial] = useState("");
  const matches = serial.trim() === device.serial;
  return <div className="overlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><h2 id="confirm-title">确认源盘身份</h2><div className="warning"><AlertTriangle/>此操作会把设备及其子设备切换为只读。</div><p>设备：<code>{device.path}</code><br/>序列号：<strong>{device.serial}</strong></p><label htmlFor="serial-confirm">手动输入完整序列号<input id="serial-confirm" autoFocus value={serial} onChange={(event) => setSerial(event.target.value)} autoComplete="off" placeholder="输入上方序列号"/></label>{error && <p className="form-error" role="alert">{error}</p>}<footer><button type="button" onClick={onClose} disabled={busy}>取消</button><button type="button" className="primary" disabled={!matches || busy} onClick={() => onConfirm(serial)}>{busy ? "正在验证…" : "确认并启用"}</button></footer></div></div>;
}

function App() {
  const [devices, setDevices] = useState(fallbackDevices); const [selected, setSelected] = useState(0); const [loading, setLoading] = useState(false); const [modal, setModal] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [environment, setEnvironment] = useState({ platform: "演示模式", hostname: "localhost", user: "当前用户", live: false }); const [caseInfo, setCaseInfo] = useState(null); const [destination, setDestination] = useState(""); const [destinationInfo, setDestinationInfo] = useState(null); const [job, setJob] = useState(null); const [message, setMessage] = useState(""); const [csrfToken, setCsrfToken] = useState("");
  const device = useMemo(() => devices[selected], [devices, selected]);
  async function refresh() { setLoading(true); try { const response = await fetch("/api/devices"); if (!response.ok) throw new Error(); const data = await response.json(); setCsrfToken(data.csrf_token || ""); setDevices(data.devices.length ? data.devices : fallbackDevices); setEnvironment(data.devices.length ? data.environment : { ...data.environment, live: false }); setSelected(0); } catch { /* Vite preview intentionally uses safe samples. */ } finally { setLoading(false); } }
  useEffect(() => { refresh(); }, []);
  async function protect(serial) { setBusy(true); setError(""); try { const data = await post("/api/protect", { device: device.path, serial }); setDevices((items) => items.map((item) => item.path === device.path ? { ...item, read_only: true } : item)); setModal(false); } catch (caught) { setError(caught.message); } finally { setBusy(false); } }
  async function post(path, body) { const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-FNOS-Token": csrfToken }, body: JSON.stringify(body) }); const data = await response.json(); if (!response.ok) throw new Error(data.error || "操作失败"); return data; }
  async function createCase() { try { setMessage("正在创建案例…"); const data = await post("/api/cases", { device: device.path, serial: device.serial, filesystem: device.filesystem }); setCaseInfo(data); setMessage("恢复案例已创建。"); } catch (e) { setMessage(e.message); } }
  async function inspectTarget() { try { const data = await post("/api/destination", { path: destination, source_device: device.path }); setDestinationInfo(data); setMessage("目标目录验证通过。"); } catch (e) { setDestinationInfo(null); setMessage(e.message); } }
  async function createJob() { try { const sourceRoot = document.getElementById("source-root").value; const paths = document.getElementById("paths").value.split(",").map(x => x.trim()).filter(Boolean); const created = await post("/api/jobs", { case_id: caseInfo.case_id, kind: "copy", parameters: { source_device: device.path, source_root: sourceRoot, destination, paths } }); await post("/api/jobs/start", { case_id: caseInfo.case_id, job_id: created.job_id }); setJob({ ...created, status: "starting" }); setMessage("复制任务已在后台启动。"); } catch (e) { setMessage(e.message); } }
  async function control(action) { try { const data = await post("/api/jobs/control", { case_id: caseInfo.case_id, job_id: job.job_id, action }); if (action === "resume") await post("/api/jobs/start", { case_id: caseInfo.case_id, job_id: job.job_id }); setJob({ ...data, status: action === "resume" ? "starting" : data.status }); setMessage(`任务操作已提交：${action}`); } catch (e) { setMessage(e.message); } }
  return <div className="app"><Sidebar/><main><header><div><span className="eyebrow">安全恢复工作台</span><h1>数据恢复控制台</h1></div><p><CheckCircle2/> {environment.live ? "本机服务已连接" : "安全演示模式"}<span/>主机：{environment.hostname}<span/>平台：{environment.platform}</p></header><Workflow/><div className="grid"><DeviceTable devices={devices} selected={selected} onSelect={(value) => { setSelected(value); setCaseInfo(null); setDestinationInfo(null); setJob(null); }} onRefresh={refresh} loading={loading}/><DeviceDetail device={device} live={environment.live} caseInfo={caseInfo} onCreateCase={createCase} onProtect={() => { setError(""); setModal(true); }}/><GuidedRecovery device={device} caseInfo={caseInfo} destination={destination} setDestination={setDestination} onInspect={inspectTarget} destinationInfo={destinationInfo} onCreateJob={createJob} job={job} onControl={control} message={message}/><Summary/></div></main>{modal && <ConfirmModal device={device} busy={busy} error={error} onClose={() => setModal(false)} onConfirm={protect}/>}</div>;
}

createRoot(document.getElementById("root")).render(<React.StrictMode><App/></React.StrictMode>);
