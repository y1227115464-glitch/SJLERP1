import { useEffect, useState } from 'react';
import { Alert, App as AntApp, Button, Card, Form, Modal, Popconfirm, Select, Space, Table, Tag, Upload } from 'antd';
import { CheckOutlined, DownloadOutlined, FileOutlined, InboxOutlined, PlayCircleOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import { api, download, errorText } from './api';
import { actionLabels, resourceLabels, dateTime, EmptyState, ErrorNotice, PageHeading, usePagedList } from './common';
import type { Attachment, Audit, Job, Notification, Store, User } from './types';
const scoped = (path: string, store: string) => store === 'all' ? path : `${path}?store_id=${encodeURIComponent(store)}`;
const jobStatuses = { queued: { label: '等待执行', color: 'default' }, running: { label: '执行中', color: 'processing' }, succeeded: { label: '已完成', color: 'success' }, failed: { label: '失败', color: 'error' } };
export function JobsPage({ user, stores, selectedStore }: { user: User; stores: Store[]; selectedStore: string }) {
  const resource = usePagedList<Job>(scoped('/jobs', selectedStore));
  const [running, setRunning] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [detail, setDetail] = useState<Job | null>(null);
  const { message } = AntApp.useApp();
  const canRun = user.permissions.includes('jobs.run');
  const active = resource.data?.items.some(job => job.status === 'queued' || job.status === 'running');
  useEffect(() => { if (!active) return; const timer = setInterval(resource.reload, 5000); return () => clearInterval(timer); }, [active, resource.reload]);
  const run = async () => { setRunning(true); try { await api('/jobs', { method: 'POST', body: { kind: 'workspace_check', ...(selectedStore !== 'all' ? { store_id: selectedStore } : {}) } }); message.success('检查任务已提交，可在列表查看执行状态'); resource.reload(); } catch (cause) { message.error(errorText(cause)); } finally { setRunning(false); } };
  const retry = async (job: Job) => { setRetrying(job.id); try { await api(`/jobs/${job.id}/retry`, { method: 'POST' }); message.success('任务已重新提交'); resource.reload(); } catch (cause) { message.error(errorText(cause)); } finally { setRetrying(null); } };
  return <><PageHeading eyebrow="BACKGROUND OPERATIONS" title="后台任务" description="查看任务状态与失败原因，验证工作空间的后台执行和通知链路。" extra={canRun && <Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={run}>运行工作空间检查</Button>} />
    <Alert className="page-notice" type="info" showIcon title="工作空间检查已开放" description={`新检查归属：${selectedStore === 'all' ? '当前账号' : stores.find(store => store.id === selectedStore)?.name ?? '所选店铺'}。列表按所选店铺筛选；执行中的任务每 5 秒刷新。`} />
    <ErrorNotice error={resource.error} retry={resource.reload} /><Card className="section-card" title="任务记录" extra={<Button icon={<ReloadOutlined />} onClick={resource.reload}>刷新</Button>}><Table<Job> dataSource={resource.data?.items ?? []} rowKey="id" loading={resource.loading} pagination={resource.pagination} scroll={{ x: 1150 }} locale={{ emptyText: <EmptyState text="尚无后台任务，可运行一次工作空间检查。" /> }} columns={[
      { title: '任务', dataIndex: 'kind', render: (value: string, record) => <div><strong>{value === 'workspace_check' ? '工作空间运行检查' : value}</strong><small className="cell-secondary mono">{record.id.slice(0, 8)}</small></div> },
      { title: '所属范围', dataIndex: 'store_id', render: (value: string | null) => value ? stores.find(store => store.id === value)?.name ?? '授权店铺' : '账号工作空间' },
      { title: '状态', dataIndex: 'status', render: (status: Job['status']) => <Tag bordered={false} color={jobStatuses[status].color}>{jobStatuses[status].label}</Tag> },
      { title: '执行次数', dataIndex: 'attempts', width: 100 }, { title: '创建时间', dataIndex: 'created_at', render: dateTime, width: 170 }, { title: '完成时间', dataIndex: 'finished_at', render: dateTime, width: 170 },
      { title: '操作', key: 'actions', width: 165, render: (_: unknown, record) => <Space size={0}><Button type="link" onClick={() => setDetail(record)}>详情</Button>{record.status === 'failed' && canRun && <Popconfirm title="重新执行此任务？" onConfirm={() => retry(record)} okText="重新执行" cancelText="取消"><Button type="link" loading={retrying === record.id}>重试</Button></Popconfirm>}</Space> },
    ]} /></Card>
    <Modal title="任务详情" open={!!detail} footer={<Button onClick={() => setDetail(null)}>关闭</Button>} onCancel={() => setDetail(null)}><dl className="detail-list"><dt>任务编号</dt><dd className="mono">{detail?.id}</dd><dt>开始时间</dt><dd>{dateTime(detail?.started_at)}</dd><dt>完成时间</dt><dd>{dateTime(detail?.finished_at)}</dd></dl>{detail?.error_message && <Alert type="error" showIcon title="任务失败" description={detail.error_message} />}{detail?.result != null && <><p>执行结果</p><pre className="result-json">{JSON.stringify(detail.result, null, 2)}</pre></>}</Modal>
  </>;
}
export function NotificationsPage({ onUnread }: { onUnread: (count: number) => void }) {
  const resource = usePagedList<Notification>('/notifications');
  const [reading, setReading] = useState<string | null>(null);
  const { message } = AntApp.useApp();
  const markRead = async (notification: Notification) => { setReading(notification.id); try { await api(`/notifications/${notification.id}/read`, { method: 'POST' }); resource.reload(); const current = await api<{ unread_notifications: number }>('/workspace'); onUnread(current.unread_notifications); } catch (cause) { message.error(errorText(cause)); } finally { setReading(null); } };
  return <><PageHeading eyebrow="NOTIFICATION INBOX" title="站内通知" description="只展示发送给当前账号的通知，及时跟进任务结果与后续工作。" extra={<Button icon={<ReloadOutlined />} onClick={resource.reload}>刷新通知</Button>} /><ErrorNotice error={resource.error} retry={resource.reload} /><Card className="section-card"><Table<Notification> dataSource={resource.data?.items ?? []} rowKey="id" loading={resource.loading} pagination={resource.pagination} scroll={{ x: 700 }} rowClassName={item => item.is_read ? '' : 'unread-row'} locale={{ emptyText: <EmptyState text="暂无通知。后台任务完成后，结果提醒会出现在这里。" /> }} columns={[
      { title: '通知内容', dataIndex: 'title', render: (value: string, record) => <div className="notification-cell"><strong>{!record.is_read && <span className="unread-dot" />}{value}</strong><p>{record.message}</p>{record.task_id && <Button type="link" href="#workspace">前往工作台</Button>}</div> }, { title: '时间', dataIndex: 'created_at', width: 170, render: dateTime },
      { title: '状态', dataIndex: 'is_read', width: 130, render: (value: boolean, record) => value ? <span className="subtle-text"><CheckOutlined /> 已读</span> : <Button type="link" loading={reading === record.id} onClick={() => markRead(record)}>标为已读</Button> },
    ]} /></Card></>;
}
function fileSize(size: number) { return size < 1024 ? `${size} B` : size < 1024 ** 2 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1024 ** 2).toFixed(1)} MB`; }
export function AttachmentsPage({ user, stores, selectedStore }: { user: User; stores: Store[]; selectedStore: string }) {
  const resource = usePagedList<Attachment>(scoped('/attachments', selectedStore));
  const [uploadOpen, setUploadOpen] = useState(false); const [file, setFile] = useState<File | null>(null); const [uploading, setUploading] = useState(false); const [downloading, setDownloading] = useState<string | null>(null); const [error, setError] = useState('');
  const [form] = Form.useForm<{ store_id?: string }>(); const { message } = AntApp.useApp();
  const upload = async (values: { store_id?: string }) => { if (!file) { setError('请先选择需要上传的附件。'); return; } setUploading(true); setError(''); const body = new FormData(); body.append('file', file); if (values.store_id) body.append('store_id', values.store_id); try { await api('/attachments', { method: 'POST', body }); message.success('附件已上传'); setUploadOpen(false); setFile(null); resource.reload(); } catch (cause) { setError(errorText(cause)); } finally { setUploading(false); } };
  return <><PageHeading eyebrow="DOCUMENT LIBRARY" title="附件中心" description="归档业务资料与凭证，下载权限随所属店铺范围控制。" extra={user.permissions.includes('files.upload') && <Button type="primary" icon={<UploadOutlined />} onClick={() => { setUploadOpen(true); setFile(null); setError(''); form.resetFields(); form.setFieldsValue({ store_id: selectedStore === 'all' ? undefined : selectedStore }); }}>上传附件</Button>} />
    <Alert className="page-notice" type="info" showIcon title="当前用于资料存档" description="此处上传不会解析订单、广告或其他业务报表；报表校验与入库将在数据导入中心开放。列表按顶部店铺筛选。" /><ErrorNotice error={resource.error} retry={resource.reload} />
    <Card className="section-card" title="已归档附件" extra={<Button icon={<ReloadOutlined />} onClick={resource.reload}>刷新</Button>}><Table<Attachment> dataSource={resource.data?.items ?? []} rowKey="id" loading={resource.loading} pagination={resource.pagination} scroll={{ x: 850 }} locale={{ emptyText: <EmptyState text="暂无附件，可上传店铺资料或业务凭证。" /> }} columns={[
      { title: '文件名', dataIndex: 'filename', render: (value: string) => <div className="file-cell"><FileOutlined /><strong>{value}</strong></div> }, { title: '所属范围', dataIndex: 'store_id', render: (value: string | null) => value ? stores.find(store => store.id === value)?.name ?? '授权店铺' : '上传者个人' }, { title: '大小', dataIndex: 'size_bytes', render: fileSize, width: 100 }, { title: '上传时间', dataIndex: 'created_at', render: dateTime, width: 175 },
      { title: '操作', key: 'actions', width: 115, render: (_: unknown, record) => <Button type="link" icon={<DownloadOutlined />} loading={downloading === record.id} onClick={async () => { setDownloading(record.id); try { await download(`/attachments/${record.id}/download`, record.filename); } catch (cause) { message.error(errorText(cause)); } finally { setDownloading(null); } }}>下载</Button> },
    ]} /></Card>
    <Modal title="上传业务附件" open={uploadOpen} onCancel={() => { if (!uploading) setUploadOpen(false); }} footer={null} destroyOnHidden><ErrorNotice error={error} /><Form form={form} layout="vertical" onFinish={upload}><Form.Item name="store_id" label="所属店铺" extra="不选店铺时保存为个人附件，仅上传者和公司管理员可访问。"><Select allowClear placeholder="个人附件（不关联店铺）" options={stores.map(store => ({ value: store.id, label: store.name }))} /></Form.Item><Form.Item label="附件文件" required><Upload.Dragger beforeUpload={value => { setFile(value); setError(''); return false; }} maxCount={1} fileList={file ? [{ uid: 'selected', name: file.name, status: 'done' }] : []} onRemove={() => { setFile(null); return true; }} disabled={uploading}><p className="ant-upload-drag-icon"><InboxOutlined /></p><p className="ant-upload-text">点击选择或拖入文件</p><p className="ant-upload-hint">每次上传一个文件，服务端将校验文件大小及格式。</p></Upload.Dragger></Form.Item><div className="form-footer"><Button onClick={() => setUploadOpen(false)} disabled={uploading}>取消</Button><Button type="primary" htmlType="submit" loading={uploading} disabled={!file}>上传并归档</Button></div></Form></Modal>
  </>;
}
export function AuditPage({ selectedStore }: { selectedStore: string }) {
  const resource = usePagedList<Audit>(scoped('/audit-logs', selectedStore));
  return <><PageHeading eyebrow="ACTIVITY AUDIT" title="操作日志" description="保留所选店铺权限范围内的关键操作记录，变更过程可追溯。" extra={<Button icon={<ReloadOutlined />} onClick={resource.reload}>刷新日志</Button>} /><ErrorNotice error={resource.error} retry={resource.reload} /><Card className="section-card" title="审计记录"><Table<Audit> dataSource={resource.data?.items ?? []} rowKey="id" loading={resource.loading} pagination={resource.pagination} scroll={{ x: 1000 }} locale={{ emptyText: <EmptyState text="当前权限范围内暂无操作日志。" /> }} columns={[
      { title: '操作时间', dataIndex: 'created_at', render: dateTime, width: 180 }, { title: '操作人', dataIndex: 'actor_name', width: 140, render: (value: string) => value || '系统' }, { title: '操作摘要', dataIndex: 'summary', width: 360 }, { title: '操作类型', dataIndex: 'action', render: (value: string) => <Tag>{actionLabels[value] ?? value}</Tag> }, { title: '关联记录', dataIndex: 'resource_type', render: (value: string, record) => <div>{resourceLabels[value] ?? value}<small className="cell-secondary mono">{record.resource_id ?? '—'}</small></div> },
    ]} /></Card></>;
}
