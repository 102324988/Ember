import { useCallback, useEffect, useRef, useState } from 'react';
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display';
import { LIVE2D_CONFIG } from './live2dConfig';

// Expose PIXI to window for the plugin
window.PIXI = PIXI;
Live2DModel.registerTicker(PIXI.Ticker);

const applyExpressionIfAvailable = (model, expressionName) => {
    if (!expressionName || typeof model?.expression !== 'function') return;

    try {
        model.expression(expressionName);
    } catch (error) {
        console.warn("Live2D expression unavailable:", { expressionName, error });
    }
};

const DEFAULT_MODEL_DISPLAY = {
    scale: 1,
    offset_x: 0,
    offset_y: 0,
    anchor: { x: 0.5, y: 0.5 },
    auto_fit: true,
};

const normalizeModelDisplay = (display) => ({
    scale: Number.isFinite(display?.scale) ? display.scale : DEFAULT_MODEL_DISPLAY.scale,
    offset_x: Number.isFinite(display?.offset_x) ? display.offset_x : DEFAULT_MODEL_DISPLAY.offset_x,
    offset_y: Number.isFinite(display?.offset_y) ? display.offset_y : DEFAULT_MODEL_DISPLAY.offset_y,
    anchor: {
        x: Number.isFinite(display?.anchor?.x) ? display.anchor.x : DEFAULT_MODEL_DISPLAY.anchor.x,
        y: Number.isFinite(display?.anchor?.y) ? display.anchor.y : DEFAULT_MODEL_DISPLAY.anchor.y,
    },
    auto_fit: typeof display?.auto_fit === 'boolean' ? display.auto_fit : DEFAULT_MODEL_DISPLAY.auto_fit,
});

const getViewportSize = () => ({
    width: window.innerWidth || LIVE2D_CONFIG.canvas.width,
    height: window.innerHeight || LIVE2D_CONFIG.canvas.height,
});

const Live2DViewer = ({ currentEmotion, audio, modelPath, modelDisplay, adjustMode, onDisplayChange, onTouch }) => {
    const canvasRef = useRef(null);
    const appRef = useRef(null);
    const modelRef = useRef(null);
    const baseScaleRef = useRef(1);
    const dragRef = useRef(null);
    const modelDisplayRef = useRef(modelDisplay);
    const [modelLoaded, setModelLoaded] = useState(false);

    // Refs for touch logic
    const onTouchRef = useRef(onTouch);
    const lastTouchTimeRef = useRef(0);

    useEffect(() => { onTouchRef.current = onTouch; }, [onTouch]);
    useEffect(() => { modelDisplayRef.current = modelDisplay; }, [modelDisplay]);

    const applyDisplayToModel = useCallback((display) => {
        const app = appRef.current;
        const model = modelRef.current;
        if (!app || !model) return;

        const normalizedDisplay = normalizeModelDisplay(display);
        model.anchor.set(normalizedDisplay.anchor.x, normalizedDisplay.anchor.y);
        model.x = (app.renderer.width / 2) + normalizedDisplay.offset_x;
        model.y = (app.renderer.height / 2) + normalizedDisplay.offset_y;
        model.scale.set(baseScaleRef.current * normalizedDisplay.scale);
    }, []);

    const keepModelInViewport = useCallback((margin = 24) => {
        const app = appRef.current;
        const model = modelRef.current;
        if (!app || !model || typeof model.getBounds !== 'function') return;

        const bounds = model.getBounds();
        if (!bounds) return;

        const viewportWidth = app.renderer.width;
        const viewportHeight = app.renderer.height;
        let dx = 0;
        let dy = 0;

        if (bounds.left < margin) {
            dx = margin - bounds.left;
        } else if (bounds.right > viewportWidth - margin) {
            dx = (viewportWidth - margin) - bounds.right;
        }

        if (bounds.top < margin) {
            dy = margin - bounds.top;
        } else if (bounds.bottom > viewportHeight - margin) {
            dy = (viewportHeight - margin) - bounds.bottom;
        }

        if (dx !== 0) model.x += dx;
        if (dy !== 0) model.y += dy;
    }, []);

    const applyDisplayWithAutoFit = useCallback((display) => {
        const normalizedDisplay = normalizeModelDisplay(display);
        applyDisplayToModel(normalizedDisplay);
        if (normalizedDisplay.auto_fit !== false) {
            keepModelInViewport(24);
        }
    }, [applyDisplayToModel, keepModelInViewport]);

    const recalculateBaseScale = useCallback(() => {
        const app = appRef.current;
        const model = modelRef.current;
        if (!app || !model) return;

        model.scale.set(1);
        const { fitPadding, scale } = LIVE2D_CONFIG.model;
        const scaleX = app.renderer.width / model.width;
        const scaleY = app.renderer.height / model.height;
        if (!Number.isFinite(scaleX) || !Number.isFinite(scaleY)) return;

        baseScaleRef.current = Math.min(scaleX, scaleY) * (fitPadding ?? 1) * scale;
    }, []);

    // 音频分析相关
    const analyserRef = useRef(null);
    const audioContextRef = useRef(null);
    const lastValueRef = useRef(0);
    const lastTargetRef = useRef(0); // 预平滑音频输入
    const lastFormRef = useRef(0); // 嘴型(MouthForm)平滑
    const velocityRef = useRef(0); // 物理速度引用
    const closeDelayCounterRef = useRef(0); // 闭嘴延迟计数器

    // 口型同步辅助逻辑
    useEffect(() => {
        if (!audio || !modelLoaded || !modelRef.current || !LIVE2D_CONFIG.lipSync.enabled) return;

        // 初始化 AudioContext
        if (!audioContextRef.current) {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            audioContextRef.current = new AudioContext();
        }
        const context = audioContextRef.current;
        if (context.state === 'suspended') context.resume();

        // 创建分析器
        if (!analyserRef.current) {
            analyserRef.current = context.createAnalyser();
            analyserRef.current.fftSize = 512; // 增加分辨率以便区分频率
        }
        const analyser = analyserRef.current;

        // 尝试连接音频源
        let source;
        try {
            source = context.createMediaElementSource(audio);
            source.connect(analyser);
            analyser.connect(context.destination);
        } catch {
            // 已连接则忽略
        }

        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        const { gain, minVolume, humanly, spring, phoneme } = LIVE2D_CONFIG.lipSync;

        // 每帧更新口型
        const updateMouth = () => {
            if (!modelRef.current?.internalModel?.coreModel) return;

            analyser.getByteFrequencyData(dataArray);

            let voiceSum = 0;
            const [start, end] = humanly.voiceRange;
            for (let i = start; i < end; i++) voiceSum += dataArray[i];
            const voiceAverage = voiceSum / (end - start);

            let normalized = Math.max(0, (voiceAverage - minVolume) / (255 - minVolume));
            let targetOpen = Math.pow(normalized, humanly.exponent) * gain;

            let lowSum = 0, lowCount = 0;
            let midSum = 0, midCount = 0;
            let highSum = 0, highCount = 0;

            const searchRange = Math.min(dataArray.length, 80);

            for (let i = 0; i < searchRange; i++) {
                if (i < phoneme.lowFreqBound) {
                    lowSum += dataArray[i];
                    lowCount++;
                } else if (i < phoneme.midFreqBound) {
                    midSum += dataArray[i];
                    midCount++;
                } else {
                    highSum += dataArray[i];
                    highCount++;
                }
            }

            const lowAvg = lowCount > 0 ? lowSum / lowCount : 0;
            const midAvg = midCount > 0 ? midSum / midCount : 0;
            const highAvg = highCount > 0 ? highSum / highCount : 0;
            const totalAvg = lowAvg + midAvg + highAvg;

            let targetForm = 0;
            if (totalAvg > 5 && targetOpen > 0.1) {
                const lowRatio = lowAvg / (totalAvg + 0.1);
                targetForm = (0.55 - lowRatio) * 5;
            }
            targetForm = Math.max(-1, Math.min(1.0, targetForm));

            if (targetForm < -0.3) {
                targetOpen *= 1.3;
            }
            targetOpen = Math.min(targetOpen, 1.0);

            if (targetOpen > 0.05) {
                closeDelayCounterRef.current = spring.closeDelayFrames;
            } else if (closeDelayCounterRef.current > 0) {
                closeDelayCounterRef.current--;
                targetOpen = Math.max(targetOpen, 0.1);
            }

            const smoothedTarget = lastTargetRef.current * (1 - spring.preSmoothing) + targetOpen * spring.preSmoothing;
            lastTargetRef.current = smoothedTarget;

            const smoothedForm = lastFormRef.current * (1 - phoneme.formSmoothing) + targetForm * phoneme.formSmoothing;
            lastFormRef.current = smoothedForm;

            const currentOpen = lastValueRef.current;
            const distance = smoothedTarget - currentOpen;
            const force = (distance * spring.stiffness) - (velocityRef.current * spring.damping);
            const acceleration = force / spring.mass;

            velocityRef.current += acceleration;
            let smoothedOpen = currentOpen + velocityRef.current;

            if (targetOpen === 0 && Math.abs(smoothedOpen) < 0.05 && Math.abs(velocityRef.current) < 0.05) {
                smoothedOpen = 0;
                velocityRef.current = 0;
            }
            smoothedOpen = Math.max(0, Math.min(1.0, smoothedOpen));

            lastValueRef.current = smoothedOpen;

            const coreModel = modelRef.current.internalModel.coreModel;
            coreModel.setParameterValueById('ParamMouthOpenY', smoothedOpen);
            coreModel.setParameterValueById('ParamMouthForm', smoothedForm);
        };

        const ticker = PIXI.Ticker.shared;
        ticker.add(updateMouth);

        return () => {
            ticker.remove(updateMouth);
            const coreModel = modelRef.current?.internalModel?.coreModel;
            if (coreModel) {
                setTimeout(() => {
                    if (modelRef.current?.internalModel?.coreModel) {
                        modelRef.current.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', 0);
                        modelRef.current.internalModel.coreModel.setParameterValueById('ParamMouthForm', 0);
                    }
                }, 150);
            }
            lastValueRef.current = 0;
            lastFormRef.current = 0;
        };
    }, [audio, modelLoaded]);

    useEffect(() => {
        if (!canvasRef.current) return;
        if (appRef.current) return;

        const init = async () => {
            try {
                const viewport = getViewportSize();
                const app = new PIXI.Application({
                    view: canvasRef.current,
                    width: viewport.width,
                    height: viewport.height,
                    backgroundAlpha: LIVE2D_CONFIG.pixi.transparent ? 0 : 1,
                    autoDensity: true,
                    resolution: window.devicePixelRatio || 1,
                    autoStart: LIVE2D_CONFIG.pixi.autoStart,
                });
                appRef.current = app;

                const targetPath = modelPath || LIVE2D_CONFIG.model.path;
                const publicPath = targetPath.startsWith('/models/')
                    ? `frontend/public${targetPath}`
                    : targetPath;
                console.log("Loading Live2D model:", { url: targetPath, publicPath });
                const model = await Live2DModel.from(targetPath, {
                    autoInteract: true
                });

                if (!appRef.current || appRef.current !== app) {
                    model.destroy();
                    return;
                }

                modelRef.current = model;
                app.stage.addChild(model);

                // 默认尝试开始 Idle 动作
                try {
                    model.motion('Idle');
                } catch (e) {
                    try {
                        model.motion('idle');
                    } catch (e2) {
                        console.log("No default idle motion found");
                    }
                }

                const latestViewport = getViewportSize();
                app.renderer.resize(latestViewport.width, latestViewport.height);
                recalculateBaseScale();
                applyDisplayWithAutoFit(modelDisplayRef.current);

                console.log("Live2D Model Loaded", {
                    url: targetPath,
                    modelSize: { width: model.width, height: model.height },
                    canvasSize: { width: app.renderer.width, height: app.renderer.height },
                    scale: model.scale.x,
                });
                setModelLoaded(true);

            } catch (error) {
                const targetPath = modelPath || LIVE2D_CONFIG.model.path;
                const publicPath = targetPath.startsWith('/models/')
                    ? `frontend/public${targetPath}`
                    : targetPath;
                console.error("Failed to load Live2D model:", {
                    error,
                    requestedUrl: targetPath,
                    expectedFilePath: publicPath,
                });
            }
        };

        init();

        return () => {
            if (appRef.current) {
                appRef.current.destroy(false, { children: true });
                appRef.current = null;
                modelRef.current = null;
            }
        };
    }, [applyDisplayWithAutoFit, modelPath, recalculateBaseScale]);

    useEffect(() => {
        if (!appRef.current) return;

        const handleResize = () => {
            const app = appRef.current;
            if (!app) return;

            const viewport = getViewportSize();
            app.renderer.resize(viewport.width, viewport.height);
            recalculateBaseScale();
            applyDisplayWithAutoFit(modelDisplayRef.current);
        };

        window.addEventListener('resize', handleResize);
        return () => {
            window.removeEventListener('resize', handleResize);
        };
    }, [applyDisplayWithAutoFit, modelLoaded, recalculateBaseScale]);

    useEffect(() => {
        if (modelLoaded) {
            if (adjustMode) {
                applyDisplayToModel(modelDisplay);
            } else {
                applyDisplayWithAutoFit(modelDisplay);
            }
        }
    }, [adjustMode, applyDisplayToModel, applyDisplayWithAutoFit, modelDisplay, modelLoaded]);

    useEffect(() => {
        if (modelLoaded && modelRef.current && currentEmotion) {
            console.log(`Switching emotion to: ${currentEmotion}`);
            applyExpressionIfAvailable(modelRef.current, currentEmotion);
        }
    }, [currentEmotion, modelLoaded]);

    // 鼠标追踪 —— 头部、眼球、身体跟随鼠标
    useEffect(() => {
        if (!modelLoaded || !modelRef.current || !LIVE2D_CONFIG.mouseTracking?.enabled) return;

        const { smoothing, headAngleRange, bodyAngleRange, bodyFactor } = LIVE2D_CONFIG.mouseTracking;

        // 归一化鼠标坐标（-1 ~ 1，以屏幕中心为原点）
        const mousePos = { x: 0, y: 0 };
        // 当前平滑值
        const current = { angleX: 0, angleY: 0, eyeX: 0, eyeY: 0, bodyX: 0 };

        const onMouseMove = (e) => {
            mousePos.x = (e.clientX / window.innerWidth) * 2 - 1;   // -1（左）~ 1（右）
            mousePos.y = (e.clientY / window.innerHeight) * 2 - 1;  // -1（上）~ 1（下）
        };

        window.addEventListener('mousemove', onMouseMove);

        const updateTracking = () => {
            const coreModel = modelRef.current?.internalModel?.coreModel;
            if (!coreModel) return;

            // 目标值
            const targetAngleX = mousePos.x * headAngleRange;
            const targetAngleY = -mousePos.y * headAngleRange;  // Y 轴反转：鼠标上移 → 头部抬起
            const targetEyeX = mousePos.x;
            const targetEyeY = -mousePos.y;
            const targetBodyX = mousePos.x * bodyAngleRange * bodyFactor;

            // lerp 平滑插值
            current.angleX += (targetAngleX - current.angleX) * smoothing;
            current.angleY += (targetAngleY - current.angleY) * smoothing;
            current.eyeX += (targetEyeX - current.eyeX) * smoothing;
            current.eyeY += (targetEyeY - current.eyeY) * smoothing;
            current.bodyX += (targetBodyX - current.bodyX) * smoothing;

            // 设置参数
            coreModel.setParameterValueById('ParamAngleX', current.angleX);
            coreModel.setParameterValueById('ParamAngleY', current.angleY);
            coreModel.setParameterValueById('ParamEyeBallX', current.eyeX);
            coreModel.setParameterValueById('ParamEyeBallY', current.eyeY);
            coreModel.setParameterValueById('ParamBodyAngleX', current.bodyX);
        };

        const ticker = PIXI.Ticker.shared;
        ticker.add(updateTracking);

        return () => {
            window.removeEventListener('mousemove', onMouseMove);
            ticker.remove(updateTracking);
        };
    }, [modelLoaded]);

    // 新增：触摸交互（全局事件监听）
    useEffect(() => {
        if (!modelLoaded || !modelRef.current || adjustMode || !LIVE2D_CONFIG.touchInteraction?.enabled) return;

        const onContextMenu = (e) => {
            const canvas = canvasRef.current;
            if (!canvas) return;

            // 获取点击的全局坐标
            const clientX = e.clientX;
            const clientY = e.clientY;

            // 获取 canvas 在屏幕上的可视矩形
            const rect = canvas.getBoundingClientRect();

            // 检查点击是否落在 canvas 的矩形范围内
            if (
                clientX >= rect.left &&
                clientX <= rect.right &&
                clientY >= rect.top &&
                clientY <= rect.bottom
            ) {
                // 阻止默认右键菜单弹出
                e.preventDefault();

                // 冷却防抖检查 (防止用户狂点导致 LLM 崩溃)
                const now = Date.now();
                const cooldownMs = LIVE2D_CONFIG.touchInteraction?.cooldownMs || 3000;
                if (now - lastTouchTimeRef.current < cooldownMs) {
                    console.log("Live2D Touch: Cooldown active, ignoring touch.");
                    return;
                }
                lastTouchTimeRef.current = now;

                // 计算相对画布的 Y 坐标百分比 (0 ~ 1)
                const relativeY = (clientY - rect.top) / rect.height;

                const { headRatio } = LIVE2D_CONFIG.touchInteraction;

                // 判断点击区域
                if (relativeY <= headRatio) {
                    // 摸头
                    console.log("Live2D Touch: Head");
                    if (onTouchRef.current) onTouchRef.current('head');
                } else {
                    // 摸身体
                    console.log("Live2D Touch: Body");
                    if (onTouchRef.current) onTouchRef.current('body');
                }
            }
        };

        window.addEventListener('contextmenu', onContextMenu);

        return () => {
            window.removeEventListener('contextmenu', onContextMenu);
        };
    }, [modelLoaded, adjustMode]);

    const handlePointerDown = (e) => {
        if (!adjustMode) return;
        const display = normalizeModelDisplay(modelDisplay);
        dragRef.current = {
            pointerId: e.pointerId,
            startX: e.clientX,
            startY: e.clientY,
            startOffsetX: display.offset_x,
            startOffsetY: display.offset_y,
        };
        e.currentTarget.setPointerCapture?.(e.pointerId);
        e.preventDefault();
    };

    const handlePointerMove = (e) => {
        if (!adjustMode || !dragRef.current) return;
        const rect = canvasRef.current?.getBoundingClientRect();
        const app = appRef.current;
        if (!rect || !app) return;

        const drag = dragRef.current;
        const scaleX = app.renderer.width / rect.width;
        const scaleY = app.renderer.height / rect.height;
        const display = normalizeModelDisplay(modelDisplay);
        onDisplayChange?.({
            ...display,
            offset_x: Math.round(drag.startOffsetX + ((e.clientX - drag.startX) * scaleX)),
            offset_y: Math.round(drag.startOffsetY + ((e.clientY - drag.startY) * scaleY)),
        });
        e.preventDefault();
    };

    const handlePointerUp = (e) => {
        if (!adjustMode || !dragRef.current) return;
        e.currentTarget.releasePointerCapture?.(dragRef.current.pointerId);
        dragRef.current = null;
    };

    return (
        <canvas
            id={LIVE2D_CONFIG.canvas.id}
            className={adjustMode ? 'live2d-adjust-mode' : ''}
            ref={canvasRef}
            style={LIVE2D_CONFIG.canvas.style}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
        />
    );
};

export default Live2DViewer;
