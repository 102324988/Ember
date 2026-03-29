import React, { useState, useEffect } from 'react';
import './ArchiveModal.css';

const API_BASE = 'http://localhost:8000/api/archive';

function ArchiveModal({ isOpen, onClose }) {
    const [archives, setArchives] = useState([]);
    const [loading, setLoading] = useState(false);
    const [operation, setOperation] = useState(null); // 'saving' | 'loading' | 'deleting'
    const [progress, setProgress] = useState({ message: '', percent: 0 });
    const [showCreateForm, setShowCreateForm] = useState(false);
    const [newSlotName, setNewSlotName] = useState('');
    const [newSlotDesc, setNewSlotDesc] = useState('');
    const [error, setError] = useState('');
    const [timeAccelFactor, setTimeAccelFactor] = useState(1.0);

    // 加载存档列表
    const loadArchives = async () => {
        try {
            const res = await fetch(`${API_BASE}/list`);
            const data = await res.json();
            if (data.success) {
                setArchives(data.archives || []);
            }
        } catch (err) {
            console.error('加载存档列表失败:', err);
            setError('加载存档列表失败');
        }
    };

    // 加载时间加速因子
    const fetchTimeAccel = async () => {
        try {
            const res = await fetch('http://localhost:8000/config');
            const data = await res.json();
            if (data.time_accel_factor !== undefined) {
                setTimeAccelFactor(data.time_accel_factor);
            }
        } catch (err) {
            console.error('获取时间加速因子失败:', err);
        }
    };

    // 设置时间加速因子
    const handleTimeAccelChange = async (newFactor) => {
        setTimeAccelFactor(newFactor);
        try {
            await fetch('http://localhost:8000/config/time_accel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ factor: newFactor }),
            });
        } catch (err) {
            console.error('设置时间加速因子失败:', err);
        }
    };

    useEffect(() => {
        if (isOpen) {
            loadArchives();
            fetchTimeAccel();
            setError('');
        }
    }, [isOpen]);

    // 创建存档
    const handleCreate = async () => {
        if (!newSlotName.trim()) {
            setError('请输入存档名称');
            return;
        }

        setOperation('saving');
        setProgress({ message: '正在创建存档...', percent: 0 });
        setError('');

        try {
            const res = await fetch(`${API_BASE}/create`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    slot_name: newSlotName.trim(),
                    description: newSlotDesc.trim()
                })
            });
            const data = await res.json();

            if (data.success) {
                setProgress({ message: '存档创建成功！', percent: 100 });
                setTimeout(() => {
                    setShowCreateForm(false);
                    setNewSlotName('');
                    setNewSlotDesc('');
                    loadArchives();
                    setOperation(null);
                }, 1000);
            } else {
                setError(data.error || '创建失败');
                setOperation(null);
            }
        } catch (err) {
            setError('创建存档失败: ' + err.message);
            setOperation(null);
        }
    };

    // 加载存档
    const handleLoad = async (slotName) => {
        if (!window.confirm(`确定要加载存档 "${slotName}" 吗？\n当前状态将被覆盖。`)) {
            return;
        }

        setOperation('loading');
        setProgress({ message: '正在加载存档...', percent: 0 });
        setError('');

        try {
            const res = await fetch(`${API_BASE}/load`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ slot_name: slotName })
            });
            const data = await res.json();

            if (data.success) {
                setProgress({ message: '存档加载成功！', percent: 100 });
                setTimeout(() => {
                    setOperation(null);
                    onClose();
                    // 刷新页面以应用新状态
                    window.location.reload();
                }, 1500);
            } else {
                setError(data.error || '加载失败');
                setOperation(null);
            }
        } catch (err) {
            setError('加载存档失败: ' + err.message);
            setOperation(null);
        }
    };

    // 删除存档
    const handleDelete = async (slotName) => {
        if (!window.confirm(`确定要删除存档 "${slotName}" 吗？\n此操作不可撤销。`)) {
            return;
        }

        setOperation('deleting');
        setError('');

        try {
            const res = await fetch(`${API_BASE}/${encodeURIComponent(slotName)}`, {
                method: 'DELETE'
            });
            const data = await res.json();

            if (data.success) {
                loadArchives();
            } else {
                setError(data.error || '删除失败');
            }
        } catch (err) {
            setError('删除存档失败: ' + err.message);
        } finally {
            setOperation(null);
        }
    };

    // 快速存档
    const handleQuickSave = async () => {
        setOperation('saving');
        setProgress({ message: '正在快速存档...', percent: 0 });
        setError('');

        try {
            const res = await fetch(`${API_BASE}/quick-save`, { method: 'POST' });
            const data = await res.json();

            if (data.success) {
                setProgress({ message: '快速存档成功！', percent: 100 });
                setTimeout(() => {
                    loadArchives();
                    setOperation(null);
                }, 1000);
            } else {
                setError(data.error || '快速存档失败');
                setOperation(null);
            }
        } catch (err) {
            setError('快速存档失败: ' + err.message);
            setOperation(null);
        }
    };

    // 快速读档
    const handleQuickLoad = async () => {
        if (!window.confirm('确定要快速读档吗？\n当前状态将被覆盖。')) {
            return;
        }

        setOperation('loading');
        setProgress({ message: '正在快速读档...', percent: 0 });
        setError('');

        try {
            const res = await fetch(`${API_BASE}/quick-load`, { method: 'POST' });
            const data = await res.json();

            if (data.success) {
                setProgress({ message: '快速读档成功！', percent: 100 });
                setTimeout(() => {
                    setOperation(null);
                    onClose();
                    window.location.reload();
                }, 1500);
            } else {
                setError(data.error || '快速读档失败');
                setOperation(null);
            }
        } catch (err) {
            setError('快速读档失败: ' + err.message);
            setOperation(null);
        }
    };

    // 格式化文件大小
    const formatSize = (bytes) => {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    };

    // 格式化时间
    const formatTime = (isoString) => {
        if (!isoString) return '';
        try {
            const date = new Date(isoString);
            return date.toLocaleString('zh-CN', {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch {
            return isoString;
        }
    };

    if (!isOpen) return null;

    // SVG 图标组件
    const SaveIcon = () => (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
            <path d="M17 3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4zm-5 16c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm3-10H5V5h10v4z" />
        </svg>
    );

    const LoadIcon = () => (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
            <path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z" />
        </svg>
    );

    const AddIcon = () => (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
            <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" />
        </svg>
    );

    const DeleteIcon = () => (
        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
            <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" />
        </svg>
    );

    const CloseIcon = () => (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" style={{ display: 'block' }}>
            <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" />
        </svg>
    );

    return (
        <div className="archive-modal-overlay" onClick={onClose}>
            <div className="archive-modal" onClick={e => e.stopPropagation()}>
                {/* 标题栏 */}
                <div className="archive-modal-header">
                    <h2>存档管理</h2>
                    <button className="archive-close-btn" onClick={onClose}>
                        <CloseIcon />
                    </button>
                </div>

                {/* 时间加速控制 */}
                <div className="time-accel-section">
                    <div className="time-accel-header">
                        <span className="time-accel-label">时间加速</span>
                        <span className="time-accel-value">{timeAccelFactor}x</span>
                    </div>
                    <input
                        type="range"
                        className="time-accel-slider"
                        min="0.5"
                        max="20"
                        step="0.5"
                        value={timeAccelFactor}
                        onChange={(e) => handleTimeAccelChange(parseFloat(e.target.value))}
                    />
                    <div className="time-accel-marks">
                        <span>0.5x</span>
                        <span>5x</span>
                        <span>10x</span>
                        <span>15x</span>
                        <span>20x</span>
                    </div>
                </div>

                {/* 错误提示 */}
                {error && (
                    <div className="archive-error">
                        {error}
                    </div>
                )}

                {/* 进度提示 */}
                {operation && (
                    <div className="archive-progress">
                        <div className="archive-progress-bar">
                            <div
                                className="archive-progress-fill"
                                style={{ width: `${progress.percent}%` }}
                            />
                        </div>
                        <span>{progress.message}</span>
                    </div>
                )}



                {/* 创建存档表单 */}
                {showCreateForm && (
                    <div className="archive-create-form">
                        <input
                            type="text"
                            placeholder="存档名称"
                            value={newSlotName}
                            onChange={e => setNewSlotName(e.target.value)}
                            maxLength={20}
                        />
                        <input
                            type="text"
                            placeholder="存档描述（可选）"
                            value={newSlotDesc}
                            onChange={e => setNewSlotDesc(e.target.value)}
                            maxLength={50}
                        />
                        <div className="archive-create-actions">
                            <button
                                className="archive-btn archive-btn-primary"
                                onClick={handleCreate}
                                disabled={operation || !newSlotName.trim()}
                            >
                                确认创建
                            </button>
                            <button
                                className="archive-btn archive-btn-secondary"
                                onClick={() => {
                                    setShowCreateForm(false);
                                    setNewSlotName('');
                                    setNewSlotDesc('');
                                }}
                            >
                                取消
                            </button>
                        </div>
                    </div>
                )}

                {/* 存档列表 */}
                <div className="archive-list">
                    <h3>存档列表 ({archives.length})</h3>
                    {archives.length === 0 ? (
                        <div className="archive-empty">
                            暂无存档，点击"新建存档"创建
                        </div>
                    ) : (
                        <div className="archive-gallery">
                            {/* 排序：快速存档 > 手动存档 > 自动备份 */}
                            {[...archives].sort((a, b) => {
                                const getType = (archive) => {
                                    if (archive.slot_name === 'quick_save') return 0;
                                    if (archive.slot_name?.startsWith('auto_backup')) return 2;
                                    return 1;
                                };
                                return getType(a) - getType(b);
                            }).map((archive, index) => (
                                <div
                                    key={archive.slot_name || index}
                                    className={`archive-card ${!archive.is_valid ? 'archive-invalid' : ''} ${archive.slot_name?.startsWith('auto_backup') ? 'archive-auto' : ''} ${archive.slot_name === 'quick_save' ? 'archive-quick' : ''}`}
                                >
                                    {/* 头部：名称 + 类型标签 */}
                                    <div className="archive-card-header">
                                        <span className="archive-card-name">
                                            {archive.slot_name}
                                        </span>
                                        {archive.slot_name === 'quick_save' && (
                                            <span className="archive-card-badge archive-badge-quick">快速</span>
                                        )}
                                        {archive.slot_name?.startsWith('auto_backup') && (
                                            <span className="archive-card-badge archive-badge-auto">自动</span>
                                        )}
                                        {!archive.slot_name?.startsWith('auto_backup') && archive.slot_name !== 'quick_save' && (
                                            <span className="archive-card-badge archive-badge-manual">手动</span>
                                        )}
                                    </div>

                                    {/* 内容：描述 + 时间 + 大小 */}
                                    <div className="archive-card-body">
                                        <div className="archive-card-desc">
                                            {archive.description || '无描述'}
                                        </div>
                                        <div className="archive-card-meta">
                                            <span className="archive-card-time">
                                                {formatTime(archive.created_at)}
                                            </span>
                                            {archive.file_size && (
                                                <span className="archive-card-size">
                                                    {formatSize(archive.file_size)}
                                                </span>
                                            )}
                                        </div>
                                    </div>

                                    {/* 操作区 */}
                                    <div className="archive-card-actions">
                                        <button
                                            className="archive-card-btn archive-card-btn-load"
                                            onClick={() => handleLoad(archive.slot_name)}
                                            disabled={operation || !archive.is_valid}
                                            title="加载此存档"
                                        >
                                            <LoadIcon /> 加载
                                        </button>
                                        <button
                                            className="archive-card-btn archive-card-btn-delete"
                                            onClick={() => handleDelete(archive.slot_name)}
                                            disabled={operation}
                                            title="删除此存档"
                                        >
                                            <DeleteIcon />
                                        </button>
                                    </div>

                                    {!archive.is_valid && (
                                        <div className="archive-card-error" title={archive.error_message || '存档损坏'}>
                                            存档损坏
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* 底部操作按钮 */}
                <div className="archive-footer">
                    <button
                        className="archive-btn archive-btn-primary"
                        onClick={handleQuickSave}
                        disabled={operation}
                    >
                        <SaveIcon /> 快速存档
                    </button>
                    <button
                        className="archive-btn archive-btn-secondary"
                        onClick={handleQuickLoad}
                        disabled={operation}
                    >
                        <LoadIcon /> 快速读档
                    </button>
                    <button
                        className="archive-btn archive-btn-create"
                        onClick={() => setShowCreateForm(!showCreateForm)}
                        disabled={operation}
                    >
                        <AddIcon /> 新建存档
                    </button>
                </div>
            </div>
        </div>
    );
}

export default ArchiveModal;