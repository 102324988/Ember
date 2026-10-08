import { useEffect, useRef, useState } from 'react';
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display';
import { LIVE2D_CONFIG } from './live2dConfig';

// Expose PIXI to window for the plugin
window.PIXI = PIXI;
Live2DModel.registerTicker(PIXI.Ticker);

const Live2DViewer = ({ currentEmotion, audio, modelPath, onTouch }) => {
    const canvasRef = useRef(null);
    const appRef = useRef(null);
    const modelRef = useRef(null);
    const [modelLoaded, setModelLoaded] = useState(false);
    
    // Refs for touch logic
    const onTouchRef = useRef(onTouch);
    const lastTouchTimeRef = useRef(0);

    useEffect(() => { onTouchRef.current = onTouch; }, [onTouch]);

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
        } catch (e) {
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
                const app = new PIXI.Application({
                    view: canvasRef.current,
                    width: LIVE2D_CONFIG.canvas.width,
                    height: LIVE2D_CONFIG.canvas.height,
                    transparent: LIVE2D_CONFIG.pixi.transparent,
                    autoStart: LIVE2D_CONFIG.pixi.autoStart,
                });
                appRef.current = app;

                const targetPath = modelPath || LIVE2D_CONFIG.model.path;
                const model = await Live2DModel.from(targetPath, {
                    autoInteract: false
                });

                if (!appRef.current || appRef.current !== app) {
                    model.destroy();
                    return;
                }

                modelRef.current = model;
                app.stage.addChild(model);

                model.anchor.set(LIVE2D_CONFIG.model.anchor.x, LIVE2D_CONFIG.model.anchor.y);
                model.x = app.renderer.width / 2;
                model.y = app.renderer.height / 2;

                const scaleX = app.renderer.width / model.width;
                const scaleY = app.renderer.height / model.height;
                model.scale.set(Math.min(scaleX, scaleY) * LIVE2D_CONFIG.model.scale);

                console.log("Live2D Model Loaded");
                setModelLoaded(true);

                if (currentEmotion && model.expression) {
                    model.expression(currentEmotion);
                }

            } catch (error) {
                console.error("Failed to load Live2D model:", error);
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
    }, [modelPath]);

    useEffect(() => {
        if (modelLoaded && modelRef.current && currentEmotion) {
            const model = modelRef.current;
            if (model.expression) {
                console.log(`Switching emotion to: ${currentEmotion}`);
                model.expression(currentEmotion);
            }
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
        if (!modelLoaded || !modelRef.current || !LIVE2D_CONFIG.touchInteraction?.enabled) return;

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

                const { headRatio, expressions } = LIVE2D_CONFIG.touchInteraction;

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
    }, [modelLoaded]);

    return (
        <canvas
            id={LIVE2D_CONFIG.canvas.id}
            ref={canvasRef}
            style={LIVE2D_CONFIG.canvas.style}
        />
    );
};

export default Live2DViewer;
