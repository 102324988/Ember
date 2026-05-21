import React, { useEffect, useRef, useState } from 'react';
import './ArchiveModal.css';
import './ProfileModal.css';

const API_BASE = 'http://localhost:8000/api/profiles';

function ProfileModal({ isOpen, onClose, onProfileSelected, onAdjustDisplay }) {
    const [profiles, setProfiles] = useState([]);
    const [currentProfileId, setCurrentProfileId] = useState('');
    const [loading, setLoading] = useState(false);
    const [selectingId, setSelectingId] = useState('');
    const [uploading, setUploading] = useState(false);
    const [deletingId, setDeletingId] = useState('');
    const [error, setError] = useState('');
    const fileInputRef = useRef(null);

    const loadProfiles = async () => {
        setLoading(true);
        setError('');
        try {
            const res = await fetch(API_BASE);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || `HTTP ${res.status}`);
            }
            setCurrentProfileId(data.current_profile_id || '');
            setProfiles(data.profiles || []);
        } catch (err) {
            console.error('加载 profile 列表失败:', err);
            setError(`加载 profile 列表失败：${err.message || '未知错误'}`);
            setProfiles([]);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (isOpen) {
            loadProfiles();
        }
    }, [isOpen]);

    const handleSelectProfile = async (profileId) => {
        if (!profileId || profileId === currentProfileId || selectingId) return;

        setSelectingId(profileId);
        setError('');
        try {
            const res = await fetch(`${API_BASE}/select`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ profile_id: profileId }),
            });
            const data = await res.json().catch(() => ({}));

            if (!res.ok || data.success === false) {
                throw new Error(data.detail || data.error || '切换 profile 失败');
            }

            setCurrentProfileId(data.current_profile_id || profileId);
            await onProfileSelected?.();
        } catch (err) {
            console.error('切换 profile 失败:', err);
            setError(err.message || '切换 profile 失败');
        } finally {
            setSelectingId('');
        }
    };

    const handleImportClick = () => {
        if (uploading) return;
        fileInputRef.current?.click();
    };

    const handleUploadLive2D = async (event) => {
        const selectedFile = event.target.files?.[0];
        event.target.value = '';
        if (!selectedFile || uploading) return;

        setUploading(true);
        setError('');
        try {
            const formData = new FormData();
            formData.append('file', selectedFile);

            const res = await fetch(`${API_BASE}/upload-live2d`, {
                method: 'POST',
                body: formData,
            });
            const data = await res.json().catch(() => ({}));

            if (!res.ok || data.success === false) {
                throw new Error(data.detail || data.error || '导入 Live2D 模型失败');
            }

            await loadProfiles();
        } catch (err) {
            console.error('导入 Live2D 模型失败:', err);
            setError(err.message || '导入 Live2D 模型失败');
        } finally {
            setUploading(false);
        }
    };

    const handleDeleteProfile = async (event, profile) => {
        event.stopPropagation();
        if (!profile?.id || deletingId || profiles.length <= 1) return;
        if (!window.confirm(`删除 Live2D 模型「${profile.name || profile.id}」？`)) return;

        setDeletingId(profile.id);
        setError('');
        try {
            const res = await fetch(`${API_BASE}/delete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ profile_id: profile.id }),
            });
            const data = await res.json().catch(() => ({}));

            if (!res.ok || data.success === false) {
                throw new Error(data.detail || data.error || '删除 Live2D 模型失败');
            }

            await loadProfiles();
            await onProfileSelected?.();
        } catch (err) {
            console.error('删除 Live2D 模型失败:', err);
            setError(err.message || '删除 Live2D 模型失败');
        } finally {
            setDeletingId('');
        }
    };

    if (!isOpen) return null;

    const CloseIcon = () => (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" style={{ display: 'block' }}>
            <path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" />
        </svg>
    );

    return (
        <div className="archive-modal-overlay" onClick={onClose}>
            <div className="archive-modal profile-modal" onClick={e => e.stopPropagation()}>
                <div className="archive-modal-header">
                    <h2>人格管理</h2>
                    <div className="profile-header-actions">
                        <button
                            type="button"
                            className="profile-import-btn"
                            onClick={handleImportClick}
                            disabled={uploading}
                        >
                            {uploading ? '导入中...' : '导入 Live2D 模型 ZIP'}
                        </button>
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".zip"
                            onChange={handleUploadLive2D}
                            style={{ display: 'none' }}
                        />
                        <button className="archive-close-btn" onClick={onClose} title="关闭">
                            <CloseIcon />
                        </button>
                    </div>
                </div>

                {error && (
                    <div className="archive-error">
                        {error}
                    </div>
                )}

                <div className="profile-modal-body">
                    {loading ? (
                        <div className="profile-empty">正在加载 profile...</div>
                    ) : profiles.length === 0 ? (
                        <div className="profile-empty">暂无本地 profile</div>
                    ) : (
                        <div className="profile-list">
                            {profiles.map(profile => {
                                const isActive = profile.id === currentProfileId;
                                const isSelecting = profile.id === selectingId;
                                const isDeleting = profile.id === deletingId;
                                return (
                                    <div
                                        role="button"
                                        tabIndex={isActive ? -1 : 0}
                                        key={profile.id}
                                        className={`profile-card ${isActive ? 'active' : ''} ${selectingId || deletingId ? 'busy' : ''}`}
                                        onClick={() => handleSelectProfile(profile.id)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter' || e.key === ' ') {
                                                e.preventDefault();
                                                handleSelectProfile(profile.id);
                                            }
                                        }}
                                    >
                                        <span className="profile-avatar">
                                            {profile.name?.slice(0, 1) || '?'}
                                        </span>
                                        <span className="profile-info">
                                            <span className="profile-name">{profile.name}</span>
                                            <span className="profile-path">{profile.model_path}</span>
                                        </span>
                                        <span className="profile-card-actions">
                                            <span className={`profile-status ${isActive ? 'active' : ''}`}>
                                                {isActive ? '使用中' : isSelecting ? '切换中...' : '切换'}
                                            </span>
                                            {isActive && (
                                                <button
                                                    type="button"
                                                    className="profile-delete-btn"
                                                    onClick={(event) => handleDeleteProfile(event, profile)}
                                                    disabled={profiles.length <= 1 || Boolean(deletingId)}
                                                    title={profiles.length <= 1 ? '至少需要保留一个 Live2D 模型' : '删除'}
                                                >
                                                    {isDeleting ? '...' : '删除'}
                                                </button>
                                            )}
                                        </span>
                                        {isActive && (
                                            <button
                                                type="button"
                                                className="profile-adjust-btn"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onAdjustDisplay?.(profile);
                                                }}
                                            >
                                                调整显示位置
                                            </button>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

export default ProfileModal;
