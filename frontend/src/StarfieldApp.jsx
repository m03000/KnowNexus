import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import * as THREE from 'three';
import './StarfieldApp.css';

// Expanded-memory nodes share one lightweight raycast geometry. Their visible
// bodies are GPU-batched below, so increasing the loaded history does not create
// one geometry allocation per memory point.
const MEMORY_HIT_GEOMETRY = new THREE.SphereGeometry(1, 5, 5);

// ====================================================================
//  安全 Markdown 渲染器（动态导入，缺失时不崩溃、降级为 <pre>）
// ====================================================================
function MarkdownRenderer({ content, onNavigateWiki, onNavigateDocument, onNavigateNote }) {
  const [MD, setMD] = useState(null);
  const [gfm, setGfm] = useState(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      import('react-markdown').then(m => m.default).catch(() => null),
      import('remark-gfm').then(m => m.default).catch(() => null),
    ]).then(([md, gf]) => {
      if (!cancelled) { setMD(() => md); setGfm(() => gf); }
    });
    return () => { cancelled = true; };
  }, []);

  if (!MD) {
    return (
      <pre style={{
        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        fontSize: 13, lineHeight: 1.85, color: '#e8ecff', fontFamily: 'inherit',
      }}>{content || ''}</pre>
    );
  }

  const components = {
    a: ({ href = '', children, ...props }) => (
      <a {...props} href={href} target={href.startsWith('wiki://') ? undefined : '_blank'} rel="noopener noreferrer" onClick={(event) => {
        event.preventDefault();
        if (href.startsWith('wiki://page/')) {
          onNavigateWiki?.(decodeURIComponent(href.slice('wiki://page/'.length)));
          return;
        }
        if (href.startsWith('document://')) {
          onNavigateDocument?.(decodeURIComponent(href.slice('document://'.length)));
          return;
        }
        if (href.startsWith('note://')) {
          onNavigateNote?.(decodeURIComponent(href.slice('note://'.length)));
          return;
        }
        if (href) window.open(href, '_blank', 'noopener,noreferrer');
      }}>{children}</a>
    ),
  };
  return <MD remarkPlugins={gfm ? [gfm] : []} urlTransform={(url) => url} components={components}>{content}</MD>;
}

// 整体空间尺度
const DOMAIN_SPHERE_R = 820;    // N 个主节点（领域中心）所在球面的半径
const SPHERE_RADIUS = 1600;     // 整体边界球半径（外轮廓约束，不可见）
// 每个领域簇的半径：领域中心半径 + 簇半径 = 边界球，簇边缘恰好抵达球面

// 单球(总览)模式的空间尺度
const R_SINGLE = 900;           // 单球模式：所有节点随机分布的球半径（饱满不空）
const R_INNER = 450;            // 单球模式：domain 主节点固定的内半径（球内非球面）

// ===== 星空色节点配色 =====
const STAR_COLORS = {
  domain: '#a882ff',   // 紫蓝主星（已被下方 DOMAIN_PALETTE 逐领域覆盖）
  chapter: '#64b4ff',  // 青蓝
  theory: '#ffb464',   // 暖橙
  tech: '#64e6c8',     // 青绿
};

// 主节点（领域）配色：5 种星云行星色。柔和、发光、彼此区分，
// 且色相与普通节点（青/橙/青绿）拉开，融入星空不突兀。
const DOMAIN_PALETTE = [
  '#ff9ec4', // 玫瑰星云粉
  '#ffd58f', // 暖金星（淡金）
  '#9db4ff', // 长春花蓝
  '#c9a6ff', // 紫晶
  '#93e6c2', // 薄荷青
];

const GOLD = '#ffd76b';
const GOLD_RGB = { r: 255, g: 215, b: 107 };

const TYPE_LABELS = {
  domain: '领域',
  chapter: '章节',
  theory: '理论',
  tech: '技术',
};

const ICONS = {
  domain: '📁',
  chapter: '📂',
  theory: '📄',
  tech: '⚙️',
};

const hexToRgb = (hex) => {
  const m = hex.replace('#', '').match(/.{2}/g);
  if (!m) return { r: 200, g: 200, b: 200 };
  return { r: parseInt(m[0], 16), g: parseInt(m[1], 16), b: parseInt(m[2], 16) };
};

const rgba = (c, a = 1) => `rgba(${c.r},${c.g},${c.b},${a})`;

// ====================================================================
//  星空背景组件（视频背景 + 星点闪烁 + 流星）—— 始终在 3D canvas 下层
// ====================================================================
function StarfieldBackground({ opacity = 1 }) {
  const overlayCanvasRef = useRef(null);

  useEffect(() => {
    const canvas = overlayCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    let width = 0;
    let height = 0;
    let starsFar = [];
    let starsMid = [];
    let meteors = [];
    let rafId;
    let previousFrameAt = 0;

    const rand = (min, max) => Math.random() * (max - min) + min;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      // 用父容器（.sf-graph-canvas）尺寸，保证画布铺满整个图谱区
      const parent = canvas.parentElement;
      const rect = parent ? parent.getBoundingClientRect() : canvas.getBoundingClientRect();
      width = Math.max(rect.width, 100);
      height = Math.max(rect.height, 100);
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // 远层（密集小点）
      starsFar = [];
      const farCount = Math.floor((width * height) / 1500);
      for (let i = 0; i < farCount; i++) {
        starsFar.push({
          x: Math.random() * width,
          y: Math.random() * height,
          r: rand(0.2, 0.7),
          alpha: rand(0.2, 0.6),
          twinkle: rand(0.003, 0.012),
          phase: Math.random() * Math.PI * 2,
        });
      }
      // 中层（亮星，带光晕）
      starsMid = [];
      const midCount = Math.floor((width * height) / 6000);
      for (let i = 0; i < midCount; i++) {
        starsMid.push({
          x: Math.random() * width,
          y: Math.random() * height,
          r: rand(0.8, 1.8),
          alpha: rand(0.5, 1.0),
          twinkle: rand(0.008, 0.02),
          phase: Math.random() * Math.PI * 2,
          bright: Math.random() > 0.7,
          hue: Math.random() > 0.5 ? '180,200,255' : '255,220,180',
        });
      }
    };

    resize();
    window.addEventListener('resize', resize);

    const spawnMeteor = () => {
      const fromLeft = Math.random() > 0.5;
      meteors.push({
        x: fromLeft ? -50 : width + 50,
        y: Math.random() * height * 0.6,
        vx: fromLeft ? rand(4, 7) : -rand(4, 7),
        vy: rand(0.5, 2),
        life: 1,
        trail: [],
      });
    };

    let frame = 0;
    const render = (now = 0) => {
      if (now - previousFrameAt < 32) {
        rafId = requestAnimationFrame(render);
        return;
      }
      previousFrameAt = now;
      frame++;
      ctx.clearRect(0, 0, width, height);

      // ===== 1. 远层星点（密集暗点）=====
      for (const s of starsFar) {
        const tw = Math.sin(frame * s.twinkle + s.phase) * 0.3 + 0.7;
        ctx.fillStyle = `rgba(255,255,255,${s.alpha * tw})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fill();
      }

      // ===== 2. 中层星点（亮星带光晕）=====
      for (const s of starsMid) {
        const tw = Math.sin(frame * s.twinkle + s.phase) * 0.4 + 0.6;
        const a = s.alpha * tw;
        if (s.bright) {
          const grad = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.r * 5);
          grad.addColorStop(0, `rgba(${s.hue},${a})`);
          grad.addColorStop(0.4, `rgba(${s.hue},${a * 0.4})`);
          grad.addColorStop(1, `rgba(${s.hue},0)`);
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(s.x, s.y, s.r * 5, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.fillStyle = `rgba(${s.hue},${a})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fill();
      }

      // ===== 6. 流星 =====
      if (Math.random() < 0.01 && meteors.length < 3) spawnMeteor();
      meteors = meteors.filter(m => m.life > 0);
      for (const m of meteors) {
        m.trail.push({ x: m.x, y: m.y });
        if (m.trail.length > 20) m.trail.shift();

        for (let i = 0; i < m.trail.length; i++) {
          const t = m.trail[i];
          const tAlpha = (i / m.trail.length) * m.life * 0.8;
          const tR = (i / m.trail.length) * 1.8 + 0.3;
          ctx.fillStyle = `rgba(200,220,255,${tAlpha})`;
          ctx.beginPath();
          ctx.arc(t.x, t.y, tR, 0, Math.PI * 2);
          ctx.fill();
        }

        const headGrad = ctx.createRadialGradient(m.x, m.y, 0, m.x, m.y, 8);
        headGrad.addColorStop(0, `rgba(255,255,255,${m.life})`);
        headGrad.addColorStop(0.5, `rgba(180,200,255,${m.life * 0.6})`);
        headGrad.addColorStop(1, 'rgba(180,200,255,0)');
        ctx.fillStyle = headGrad;
        ctx.beginPath();
        ctx.arc(m.x, m.y, 8, 0, Math.PI * 2);
        ctx.fill();

        m.x += m.vx;
        m.y += m.vy;
        m.life -= 0.007;
        if (m.x < -100 || m.x > width + 100 || m.y > height + 100) m.life = 0;
      }

      rafId = requestAnimationFrame(render);
    };

    render();
    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('resize', resize);
    };
  }, []);

  return (
    <>
      {/* 背景图片已移除；动态星点、流星和 3D 节点层保持不变。 */}
      {/* 暗色遮罩（极淡） */}
      <div className="sf-image-overlay" />
      {/* 星空动画 Canvas */}
      <canvas ref={overlayCanvasRef} className="sf-starfield-bg" style={{ opacity }} />
    </>
  );
}

// ====================================================================
//  布局函数（模块级纯函数，不依赖组件 state）
//  mode: 'clusters' = 分域多球（现有外观，保持不变）；'galaxy' = 单球总览
// ====================================================================
const applyLayout = (nodes, mode, nodeMap) => {
  const domainNodes = nodes.filter(n => n.node_type === 'domain');
  const DOMAIN_INDEX = new Map(domainNodes.map((d, i) => [d.id, i]));

  // 从任意节点向上回溯到所属 domain，返回其索引（找不到则归 0）
  const findDomainIdx = (node) => {
    let cur = node, guard = 0;
    while (cur && cur.node_type !== 'domain' && guard < 30) {
      cur = nodeMap.get(cur.parent);
      guard++;
    }
    if (cur && cur.node_type === 'domain') return DOMAIN_INDEX.get(cur.id) ?? 0;
    return 0;
  };

  const CENTER_R = DOMAIN_SPHERE_R;                 // 领域中心所在球面半径
  const normalizeVec = (v) => {
    const m = Math.hypot(v.x, v.y, v.z) || 1;
    return { x: v.x / m, y: v.y / m, z: v.z / m };
  };
  // N 个领域在球面上的中心方向（均匀/近似均匀分布）。
  // 【调整领域位置】修改此函数即可改变各领域在 3D 星图中的方位。
  // 返回值是单位向量数组（{x,y,z}），每个元素对应一个 domain 的球面方向，
  // 按顺序与 domainNodes[] 一一对应。领域中心实际坐标 = DIR[i] * DOMAIN_SPHERE_R。
  const buildDomainDirs = (count) => {
    // 单主题笔记图谱不能进入下方 count - 1 的黄金角公式，否则坐标会变成 NaN，
    // ForceGraph 会把所有节点坍缩在中心。
    if (count <= 0) return [];
    if (count === 1) return [{ x: 0, y: 0, z: 1 }];
    // ── 2～3：历史兼容 ──
    if (count === 2) return [
      { x: 0, y: 1, z: 0 },
      { x: 0, y: -1, z: 0 },
    ].map(normalizeVec);
    if (count === 3) return [
      { x: 0,      y: 1,     z: 0.001 },           // 北极
      { x: 0.866,  y: -0.5,  z: 0 },               // 南偏右 120°
      { x: -0.866, y: -0.5,  z: 0 },               // 南偏左 120°
    ].map(normalizeVec);

    // ── 4：正四面体 ──
    if (count === 4) {
      const s = 1 / Math.sqrt(3);
      return [
        { x: 1, y: 1, z: 1 },
        { x: 1, y: -1, z: -1 },
        { x: -1, y: 1, z: -1 },
        { x: -1, y: -1, z: 1 },
      ].map(v => normalizeVec({ x: v.x * s, y: v.y * s, z: v.z * s }));
    }

    // ── 5：三角双锥（最均匀 5 点分布）──
    if (count === 5) {
      const eq = Math.sqrt(2 / 3);   // 赤道点到原点距离（单位球面上）
      const dirs = [
        { x: 0, y: 1, z: 0 },                          // 0: 北极
        { x: 0, y: -1, z: 0 },                         // 1: 南极
        { x: eq,       y: 0, z: 0 },                   // 2: 赤道右
        { x: -eq / 2,  y: 0, z: eq * Math.sqrt(3)/2 },// 3: 赤道左前
        { x: -eq / 2,  y: 0, z: -eq * Math.sqrt(3)/2 },// 4: 赤道左后
      ];
      return dirs.map(normalizeVec);
    }

    // ── 6+：斐波那契黄金角螺旋（通用）──
    const golden = Math.PI * (3 - Math.sqrt(5));
    const dirs = [];
    for (let i = 0; i < count; i++) {
      const y = 1 - (i / (count - 1)) * 2;             // 1 → -1
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const theta = golden * i;
      dirs.push({ x: Math.cos(theta) * r, y, z: Math.sin(theta) * r });
    }
    return dirs;
  };
  const DIR = buildDomainDirs(domainNodes.length);
  // 簇半径：随领域数量自适应，避免多领域时簇严重重叠；
  // 3 个领域时沿用历史值 780（=1600-820），保持已有外观
  const BLOB_R = domainNodes.length <= 3
    ? (SPHERE_RADIUS - CENTER_R)
    : Math.min(SPHERE_RADIUS - CENTER_R, CENTER_R * Math.sin(Math.PI / domainNodes.length) * 0.95);

  // 在半径 R 的球体内取一个随机点
  const randInSphere = (R) => {
    const r = R * Math.cbrt(Math.random());         // cbrt 保证体积均匀
    const u = Math.random(), v = Math.random();
    const theta = 2 * Math.PI * u;
    const phi = Math.acos(2 * v - 1);
    return {
      x: r * Math.sin(phi) * Math.cos(theta),
      y: r * Math.sin(phi) * Math.sin(theta),
      z: r * Math.cos(phi),
    };
  };

  // ===== 单球(总览)模式 =====
  // domain 主节点钉在球内固定位（非最外圈球面），其余节点在球内随机分散。
  if (mode === 'galaxy') {
    const galaxyDirs = buildDomainDirs(domainNodes.length);  // 复用方向，乘内半径
    nodes.forEach(n => {
      if (n.node_type === 'domain') {
        const di = DOMAIN_INDEX.get(n.id) ?? 0;
        const d = galaxyDirs[di % galaxyDirs.length];
        n.fx = d.x * R_INNER;
        n.fy = d.y * R_INNER;
        n.fz = d.z * R_INNER;
        n.x = n.fx; n.y = n.fy; n.z = n.fz;
      } else {
        const off = randInSphere(R_SINGLE);
        n.fx = off.x; n.fy = off.y; n.fz = off.z;
        n.x = n.fx; n.y = n.fy; n.z = n.fz;
      }
    });
    // 不 return —— 继续走末尾的归一化
  } else {
  // ===== 多球(分域)模式（现有逻辑，完全不变）====
  nodes.forEach(n => {
    if (n.node_type === 'domain') {
      const di = DOMAIN_INDEX.get(n.id) ?? 0;
      const d = DIR[di % DIR.length];
      n.fx = d.x * CENTER_R;
      n.fy = d.y * CENTER_R;
      n.fz = d.z * CENTER_R;
      n.x = n.fx; n.y = n.fy; n.z = n.fz;
    } else {
      const di = findDomainIdx(n);
      const d = DIR[di % DIR.length];
      const off = randInSphere(BLOB_R);
      // 钉死在球面簇内的初始位置（fx/fy/fz），力导不移动 → 外轮廓恒定球形
      n.fx = d.x * CENTER_R + off.x;
      n.fy = d.y * CENTER_R + off.y;
      n.fz = d.z * CENTER_R + off.z;
      n.x = n.fx; n.y = n.fy; n.z = n.fz;
    }
  });
  }

  // ===== 关键：归一化到原点 =====
  // 用所有节点的**质心**（平均位置）作为归一化目标，而不是 AABB 中心。
  // 5 领域三角双锥：domain X 坐标 [0, 0, 820, -410, -410]，AABB 中心=+205 但质心=-205（视觉重心）。
  // 归一化到 AABB 中心 → 相机看 AABB 中心 → 但视觉重心在画布左偏；用户感觉仍偏右是因为
  // 多球分布时相机看 AABB 中心与视觉重心不一致。改用质心后，视觉重心=原点，相机看原点即居中。
  {
    let sumX = 0, sumY = 0, sumZ = 0, count = 0;
    for (const n of nodes) {
      sumX += n.x; sumY += n.y; sumZ += n.z;
      count++;
    }
    if (count > 0) {
      const cx = sumX / count;
      const cy = sumY / count;
      const cz = sumZ / count;
      nodes.forEach(n => {
        n.fx -= cx; n.fy -= cy; n.fz -= cz;
        n.x  -= cx; n.y  -= cy; n.z  -= cz;
      });
    }
  }
};

const NODE_TYPE_LABELS = {
  note: { note: '笔记', document: '个人文档', knowledge_point: '知识点', wiki_topic: '主题', wiki_concept: '概念', wiki_synthesis: '综合', wiki_source: '来源' },
  project: { project: '项目', module: '模块', file: '文件', class: '类', function: '函数', method: '方法', block: '代码块' },
  memory: { conversation_turn: '原文', memory_entity: '实体' },
};

const NODE_TYPE_ICONS = {
  note: { note: '📝', document: '📄', knowledge_point: '✦', wiki_topic: '🗂️', wiki_concept: '◈', wiki_synthesis: '🔗', wiki_source: '📚' },
  project: { project: '📦', module: '📁', file: '📄', class: '◫', function: 'ƒ', method: 'ƒ', block: '⌘' },
  memory: { conversation_turn: '📜', memory_entity: '◎', memory_point: '✦' },
};

const memoryTypeLabel = (type) => ({
  fact: '事实', preference: '偏好', decision: '决定', event: '事件', insight: '洞察',
}[type] || (type ? String(type) : '记忆'));

const actualNodeTypeLabel = (node, domain) => {
  if (domain === 'memory' && node.original_node_type === 'memory_point') {
    return memoryTypeLabel(node.payload?.memory_type);
  }
  return NODE_TYPE_LABELS[domain]?.[node.original_node_type]
    || node.original_node_type
    || TYPE_LABELS[node.node_type]
    || node.node_type;
};

const actualNodeTypeIcon = (node, domain) => NODE_TYPE_ICONS[domain]?.[node.original_node_type]
  || ICONS[node.node_type]
  || '📄';

const DEFAULT_RENDER_SETTINGS = {
  memoryGalaxyEnabled: true,
  memoryGalaxyStyle: 'shiyun',
  memorySpatialLayout: 'scatter',
  memoryGalaxyRotationSpeed: 0.55,
  memoryGalaxyShimmerStrength: 1.35,
  memoryGalaxyParticleLevel: 1,
  memorySpatialScale: 1,
  memoryMovementSpeed: 5,
  memoryMotionBaselineVersion: 2,
  memoryOriginalSize: 2,
  memoryOriginalBrightness: 1,
  memoryOriginalShape: 'diamond',
  memoryFactSize: 1,
  memoryFactBrightness: 1,
  memoryFactShape: 'circle',
  memoryEntitySize: 1,
  memoryEntityBrightness: 1,
  memoryEntityShape: 'circle',
  memoryClusterSpatialScale: 1,
  memoryClusterRotationSpeed: 0.4,
  memoryClusterShowLinks: false,
  memoryClusterDefaultsVersion: 3,
  memoryClusterOriginalSize: 2,
  memoryClusterOriginalBrightness: 1.2,
  memoryClusterOriginalShape: 'diamond',
  memoryClusterFactSize: 1,
  memoryClusterFactBrightness: 1.2,
  memoryClusterFactShape: 'circle',
  memoryClusterEntitySize: 1,
  memoryClusterEntityBrightness: 1.2,
  memoryClusterEntityShape: 'circle',
  memoryClusterLineColor: '#7697df',
  memoryClusterLineOpacity: 0.6,
  memoryClusterLineThickness: 4,
  memoryPrimarySize: 1,
  memoryGalaxyNodeSizeBaselineVersion: 3,
  memoryPrimaryBrightness: 0.78,
  memoryPrimaryShape: 'circle',
  memoryPrimaryColor: '#72b9ff',
  memoryInternalColor: '#9d83ff',
  memoryAgent1Color: '#63b8ff',
  memoryAgent2Color: '#63e6b0',
  memoryAgent3Color: '#ffae68',
  memoryPrimaryGlow: 'soft',
  memorySecondarySize: 0.62,
  memorySecondaryBrightness: 0.32,
  memorySecondaryShape: 'circle',
  memorySecondaryColor: '#8b79c9',
  memorySecondaryGlow: 'compact',
  generalSize: 1,
  generalBrightness: 0.7,
  generalShape: 'circle',
  generalColor: '#82a8ff',
  generalGlow: 'soft',
  noteStyleBaselineVersion: 1,
  noteTopicSize: 1.35,
  noteTopicBrightness: 1,
  noteTopicShape: 'circle',
  noteTopicColor: '#65c8ff',
  noteTopicGlow: 'soft',
  noteConceptSize: 0.78,
  noteConceptBrightness: 0.82,
  noteConceptShape: 'circle',
  noteConceptColor: '#aa8cff',
  noteConceptGlow: 'soft',
  noteDocumentSize: 1,
  noteDocumentBrightness: 0.78,
  noteDocumentShape: 'circle',
  noteDocumentColor: '#f3a765',
  noteDocumentGlow: 'soft',
  projectBlockSize: 1,
  projectBlockBrightness: 0.78,
  projectBlockShape: 'circle',
  projectBlockColor: '#64e6c8',
  projectBlockGlow: 'soft',
  projectOtherSize: 1,
  projectOtherBrightness: 0.66,
  projectOtherShape: 'circle',
  projectOtherColor: '#82a8ff',
  projectOtherGlow: 'soft',
  clustering: 1,
  lineColor: '#7697df',
  lineOpacity: 0.45,
  lineThickness: 3,
  lineThicknessBaselineVersion: 2,
  backgroundOpacity: 1,
};

const loadRenderSettings = () => {
  try {
    const stored = JSON.parse(localStorage.getItem('agentforge.graphRenderSettings') || '{}');
    const settings = { ...DEFAULT_RENDER_SETTINGS, ...stored };
    if (!stored.memoryGalaxyStyle) {
      settings.memoryGalaxyStyle = stored.memoryGalaxyEnabled === false ? 'classic' : 'shiyun';
    }
    settings.memoryGalaxyStyle = 'shiyun';
    settings.memoryGalaxyEnabled = true;
    settings.memoryGalaxyParticleLevel = [0.25, 0.5, 0.75, 1].includes(Number(settings.memoryGalaxyParticleLevel))
      ? Number(settings.memoryGalaxyParticleLevel) : 1;
    // “球状聚合（原版）”已下线；历史配置统一迁移到新的球形边界散点。
    settings.memorySpatialLayout = 'scatter';
    if (stored.memoryMotionBaselineVersion !== 2) {
      settings.memoryMovementSpeed = 5;
      settings.memoryMotionBaselineVersion = 2;
    }
    if (stored.memoryGalaxyNodeSizeBaselineVersion !== 3) {
      settings.memoryPrimarySize = 1;
      settings.memoryGalaxyNodeSizeBaselineVersion = 3;
    }
    if (stored.lineThicknessBaselineVersion !== 2) {
      settings.lineThickness = 3;
      settings.lineThicknessBaselineVersion = 2;
    }
    if (stored.memoryClusterDefaultsVersion !== 3) {
      settings.memoryClusterRotationSpeed = 0.4;
      settings.memoryClusterShowLinks = false;
      settings.memoryClusterOriginalBrightness = 1.2;
      settings.memoryClusterFactBrightness = 1.2;
      settings.memoryClusterEntityBrightness = 1.2;
      settings.memoryClusterLineOpacity = 0.6;
      settings.memoryClusterLineThickness = 4;
      settings.memoryClusterDefaultsVersion = 3;
    }
    if (stored.noteStyleBaselineVersion !== 1) {
      settings.noteTopicSize = 1.35;
      settings.noteConceptSize = 0.78;
      settings.noteDocumentSize = 1;
      settings.noteStyleBaselineVersion = 1;
    }
    ['memoryPrimaryShape', 'memorySecondaryShape', 'generalShape', 'notePointShape',
      'noteTopicShape', 'noteConceptShape', 'noteDocumentShape', 'projectBlockShape', 'projectOtherShape'].forEach((key) => {
      if (settings[key] === 'ring') settings[key] = 'circle';
    });
    ['noteTopicShape', 'noteConceptShape', 'noteDocumentShape'].forEach((key) => {
      settings[key] = ['circle', 'diamond'].includes(settings[key]) ? settings[key] : 'circle';
    });
    settings.memoryOriginalShape = ['circle', 'diamond'].includes(settings.memoryOriginalShape)
      ? settings.memoryOriginalShape : 'diamond';
    settings.memoryFactShape = ['circle', 'diamond'].includes(settings.memoryFactShape)
      ? settings.memoryFactShape : 'circle';
    settings.memoryEntityShape = ['circle', 'diamond'].includes(settings.memoryEntityShape)
      ? settings.memoryEntityShape : 'circle';
    settings.memoryClusterOriginalShape = ['circle', 'diamond'].includes(settings.memoryClusterOriginalShape)
      ? settings.memoryClusterOriginalShape : 'diamond';
    settings.memoryClusterFactShape = ['circle', 'diamond'].includes(settings.memoryClusterFactShape)
      ? settings.memoryClusterFactShape : 'circle';
    settings.memoryClusterEntityShape = ['circle', 'diamond'].includes(settings.memoryClusterEntityShape)
      ? settings.memoryClusterEntityShape : 'circle';
    return settings;
  } catch {
    return { ...DEFAULT_RENDER_SETTINGS };
  }
};

const applyPersonalizedLayout = (nodes, settings) => {
  const spread = 1 / settings.clustering;
  nodes.forEach((node) => {
    const bx = node.__baseX ?? node.x ?? 0;
    const by = node.__baseY ?? node.y ?? 0;
    const bz = node.__baseZ ?? node.z ?? 0;
    node.fx = node.x = bx * spread;
    node.fy = node.y = by * spread;
    node.fz = node.z = bz * spread;
  });
};

// 记忆图谱默认外观 v15：提升双倍星图的悬臂密度，并用亮核+柔暗外层强化球核纵深。关闭 memoryGalaxyEnabled
// 即回到 2026-09-03 之前的经典孤立散点效果，便于随时回退视觉版本。
const MEMORY_GALAXY_VERSION = 'memory-galaxy-v18';
const MEMORY_GALAXY_TILT = -0.88;
const MEMORY_GALAXY_ROTATION_SPEED = -0.00001;
const MEMORY_GALAXY_SCALE = 2;

const stableUnit = (value, salt = 0) => {
  let hash = 2166136261 ^ salt;
  const text = String(value || 'memory');
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  hash += hash << 13; hash ^= hash >>> 7;
  hash += hash << 3; hash ^= hash >>> 17; hash += hash << 5;
  return (hash >>> 0) / 4294967295;
};

const getMemorySpatialExtent = (nodeCount, scale = 1) => (
  Math.max(12000, Math.cbrt(Math.max(nodeCount, 1)) * 2000) * scale
);

const NO_NODE_LABEL = () => '';

const memoryGalaxyPosition = (node, index = 0) => {
  const key = node?.id || index;
  const progress = Math.pow(stableUnit(key, 17), 0.92);
  const radius = 82 + progress * 560;
  const armCount = 5;
  const arm = Math.floor(stableUnit(key, 29) * armCount) % armCount;
  const armAngle = arm * Math.PI * 2 / armCount;
  const widening = 0.34 + progress * 0.52;
  const branch = progress > 0.46 && stableUnit(key, 101) > 0.68
    ? (stableUnit(key, 103) > 0.5 ? 1 : -1) * (0.08 + progress * 0.16)
    : 0;
  const irregularity = Math.sin(progress * 7.5 + arm * 1.7) * 0.055;
  const angle = armAngle + progress * 1.48 + irregularity + branch
    + ((stableUnit(key, 43) + stableUnit(key, 47) + stableUnit(key, 53) - 1.5) / 1.5) * widening;
  const thickness = 135 - progress * 62;
  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius * 0.94,
    z: (stableUnit(key, 71) + stableUnit(key, 89) - 1) * thickness,
  };
};

// The real graph nodes use the same four-branch spiral skeleton as Poetry Cloud's MIT galaxy.
const shiyunMemoryGalaxyPosition = (node, index = 0) => {
  const key = node?.id || index;
  const progress = Math.min(1, -0.27 * Math.log(1 - stableUnit(key, 17) * 0.975));
  // 真实记忆星点避开中心球核，避免交互节点被核心强光吞没。
  const radius = 92 + progress * 558;
  const arm = Math.floor(stableUnit(key, 29) * 4) % 4;
  const interarm = stableUnit(key, 97) < 0.055;
  // 真实记忆主要贴在四条悬臂主脊上；只留约 5.5% 作为臂间疏星。
  const armDeviation = interarm
    ? (stableUnit(key, 43) - 0.5) * Math.PI * 0.5
    : (stableUnit(key, 43) + stableUnit(key, 47) + stableUnit(key, 53) - 1.5) * 0.34;
  const centerBlur = Math.max(0, 0.45 - progress) / 0.45;
  const angle = arm * Math.PI * 0.5 + progress * 5.2 + armDeviation
    + (interarm ? (stableUnit(key, 59) - 0.5) * 0.5 * centerBlur : 0);
  const scatterX = Math.pow(stableUnit(key, 61), 2.2)
    * (stableUnit(key, 67) < 0.5 ? -1 : 1) * (interarm ? 0.12 : 0.085) * radius;
  const scatterY = Math.pow(stableUnit(key, 73), 2.2)
    * (stableUnit(key, 79) < 0.5 ? -1 : 1) * (interarm ? 0.12 : 0.085) * radius;
  const coreScatter = centerBlur * centerBlur * 650 * (interarm ? 0.08 : 0.018);
  return {
    x: Math.cos(angle) * radius + scatterX + (stableUnit(key, 83) - 0.5) * 2 * coreScatter,
    y: Math.sin(angle) * radius + scatterY + (stableUnit(key, 87) - 0.5) * 2 * coreScatter,
    z: (stableUnit(key, 71) + stableUnit(key, 89) - 1) * radius * 0.11,
  };
};

const galaxyPositionForStyle = (node, index, style) => (style === 'shiyun'
  ? shiyunMemoryGalaxyPosition(node, index)
  : memoryGalaxyPosition(node, index));

const transformMemoryGalaxyPosition = (position, angle = 0) => {
  const cosAngle = Math.cos(angle);
  const sinAngle = Math.sin(angle);
  const rotatedX = position.x * cosAngle - position.y * sinAngle;
  const rotatedY = position.x * sinAngle + position.y * cosAngle;
  const cosTilt = Math.cos(MEMORY_GALAXY_TILT);
  const sinTilt = Math.sin(MEMORY_GALAXY_TILT);
  return {
    x: rotatedX * MEMORY_GALAXY_SCALE,
    y: (rotatedY * cosTilt - position.z * sinTilt) * MEMORY_GALAXY_SCALE,
    z: (rotatedY * sinTilt + position.z * cosTilt) * MEMORY_GALAXY_SCALE,
  };
};

const setNodePosition = (node, position) => {
  node.fx = node.x = position.x;
  node.fy = node.y = position.y;
  node.fz = node.z = position.z;
};

// 将记忆点—实体关系拆成连通分量，每个分量放进独立的动态球形空间。
// 球半径随分量节点数按立方根扩展，簇中心也随簇数量扩大，避免大数据量互相穿插。
const applyMemoryClusterLayout = (nodes, links, spatialScale = 1) => {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const neighbors = new Map(nodes.map((node) => [node.id, []]));
  links.forEach((link) => {
    const source = typeof link.source === 'object' ? link.source.id : link.source;
    const target = typeof link.target === 'object' ? link.target.id : link.target;
    if (!nodeById.has(source) || !nodeById.has(target)) return;
    neighbors.get(source).push(target);
    neighbors.get(target).push(source);
  });
  const components = [];
  const visited = new Set();
  nodes.forEach((start) => {
    if (visited.has(start.id)) return;
    const component = [];
    const queue = [start.id];
    visited.add(start.id);
    while (queue.length) {
      const id = queue.shift();
      component.push(nodeById.get(id));
      (neighbors.get(id) || []).forEach((next) => {
        if (!visited.has(next)) { visited.add(next); queue.push(next); }
      });
    }
    components.push(component);
  });
  components.sort((a, b) => b.length - a.length);
  const golden = Math.PI * (3 - Math.sqrt(5));
  const clusterCount = components.length;
  // 以近似恒定的单位体积容纳节点：节点越多，约束球越大，避免大分量挤成实心光团。
  // 数量增长项再增加一倍，并允许集群个性化空间比例独立调节。
  const clusterRadii = components.map((component) => (
    Math.max(150, 72 + Math.cbrt(Math.max(component.length, 1)) * 612) * spatialScale
  ));
  const largestRadius = Math.max(0, ...clusterRadii);
  const orbitRadius = clusterCount <= 1
    ? 0
    : Math.max(920, largestRadius * 1.18 + Math.sqrt(clusterCount) * 330);
  components.forEach((component, clusterIndex) => {
    const y = clusterCount <= 1 ? 0 : 1 - (clusterIndex / Math.max(1, clusterCount - 1)) * 2;
    const ring = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = golden * clusterIndex;
    const center = {
      x: Math.cos(angle) * ring * orbitRadius,
      y: y * orbitRadius * .72,
      z: Math.sin(angle) * ring * orbitRadius,
    };
    const radius = clusterRadii[clusterIndex];
    component.forEach((node) => {
      const px = stableUnit(node.id, 1201) * 2 - 1;
      const py = stableUnit(node.id, 1213) * 2 - 1;
      const pz = stableUnit(node.id, 1223) * 2 - 1;
      const length = Math.hypot(px, py, pz) || 1;
      const distance = Math.cbrt(stableUnit(node.id, 1231)) * radius;
      const offset = {
        x: px / length * distance,
        y: py / length * distance,
        z: pz / length * distance,
      };
      node.__memoryCluster = {
        center,
        offset,
        direction: stableUnit(`cluster:${clusterIndex}`, 1249) < .5 ? -1 : 1,
        speed: .72 + stableUnit(`cluster:${clusterIndex}`, 1259) * .56,
      };
      setNodePosition(node, {
        x: center.x + offset.x,
        y: center.y + offset.y,
        z: center.z + offset.z,
      });
    });
  });
};

const NOTE_TOPIC_TYPES = new Set(['wiki_topic']);
const NOTE_CONCEPT_TYPES = new Set(['wiki_concept', 'knowledge_point', 'wiki_synthesis']);
const NOTE_DOCUMENT_TYPES = new Set(['note', 'document', 'wiki_source']);

// 笔记图谱使用三层语义空间：主题彼此拉开，概念围绕所属主题形成较大的球状簇，
// 文档独立散布在全局空间。布局完全确定性，刷新后不会随机跳位。
const applyNoteSemanticLayout = (nodes, links) => {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const topics = nodes.filter((node) => NOTE_TOPIC_TYPES.has(node.original_node_type));
  const concepts = nodes.filter((node) => NOTE_CONCEPT_TYPES.has(node.original_node_type));
  const documents = nodes.filter((node) => NOTE_DOCUMENT_TYPES.has(node.original_node_type));
  const topicCenters = new Map();
  const placedCenters = [];
  const topicOrbit = Math.max(620, Math.cbrt(Math.max(topics.length, 1)) * 520);

  topics.forEach((topic, index) => {
    let best = null;
    let bestDistance = -1;
    for (let attempt = 0; attempt < 16; attempt += 1) {
      const key = `${topic.id}:${attempt}`;
      const x = stableUnit(key, 1301) * 2 - 1;
      const y = stableUnit(key, 1307) * 2 - 1;
      const z = stableUnit(key, 1319) * 2 - 1;
      const length = Math.hypot(x, y, z) || 1;
      const radial = topicOrbit * (.72 + stableUnit(key, 1321) * .32);
      const candidate = { x: x / length * radial, y: y / length * radial, z: z / length * radial };
      const nearest = placedCenters.length
        ? Math.min(...placedCenters.map((other) => Math.hypot(
          candidate.x - other.x, candidate.y - other.y, candidate.z - other.z,
        )))
        : Infinity;
      if (nearest > bestDistance) { best = candidate; bestDistance = nearest; }
    }
    const center = best || { x: index * 500, y: 0, z: 0 };
    topicCenters.set(topic.id, center);
    placedCenters.push(center);
    topic.__noteRole = 'topic';
    setNodePosition(topic, center);
  });

  const topicForConcept = new Map();
  links.forEach((link) => {
    const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
    const targetId = typeof link.target === 'object' ? link.target.id : link.target;
    const source = nodeById.get(sourceId);
    const target = nodeById.get(targetId);
    if (NOTE_TOPIC_TYPES.has(source?.original_node_type) && NOTE_CONCEPT_TYPES.has(target?.original_node_type)) {
      topicForConcept.set(target.id, source.id);
    } else if (NOTE_TOPIC_TYPES.has(target?.original_node_type) && NOTE_CONCEPT_TYPES.has(source?.original_node_type)) {
      topicForConcept.set(source.id, target.id);
    }
  });
  const conceptsByTopic = new Map(topics.map((topic) => [topic.id, []]));
  concepts.forEach((concept) => {
    const topicId = topicForConcept.get(concept.id);
    if (topicId && conceptsByTopic.has(topicId)) conceptsByTopic.get(topicId).push(concept);
  });
  conceptsByTopic.forEach((items, topicId) => {
    const center = topicCenters.get(topicId);
    const constraintRadius = Math.max(300, 190 + Math.cbrt(Math.max(items.length, 1)) * 150);
    items.forEach((concept) => {
      const px = stableUnit(concept.id, 1361) * 2 - 1;
      const py = stableUnit(concept.id, 1367) * 2 - 1;
      const pz = stableUnit(concept.id, 1373) * 2 - 1;
      const length = Math.hypot(px, py, pz) || 1;
      const distance = Math.cbrt(stableUnit(concept.id, 1381)) * constraintRadius;
      concept.__noteRole = 'concept';
      setNodePosition(concept, {
        x: center.x + px / length * distance,
        y: center.y + py / length * distance,
        z: center.z + pz / length * distance,
      });
    });
  });
  concepts.filter((concept) => !topicForConcept.has(concept.id)).forEach((concept) => {
    const radius = topicOrbit * 1.25;
    const x = stableUnit(concept.id, 1391) * 2 - 1;
    const y = stableUnit(concept.id, 1399) * 2 - 1;
    const z = stableUnit(concept.id, 1409) * 2 - 1;
    const length = Math.hypot(x, y, z) || 1;
    concept.__noteRole = 'concept';
    setNodePosition(concept, { x: x / length * radius, y: y / length * radius, z: z / length * radius });
  });

  const documentExtent = Math.max(topicOrbit * 1.55, Math.cbrt(Math.max(documents.length, 1)) * 430);
  documents.forEach((document) => {
    const x = stableUnit(document.id, 1423) * 2 - 1;
    const y = stableUnit(document.id, 1429) * 2 - 1;
    const z = stableUnit(document.id, 1433) * 2 - 1;
    const length = Math.hypot(x, y, z) || 1;
    const distance = Math.cbrt(stableUnit(document.id, 1439)) * documentExtent;
    document.__noteRole = 'document';
    setNodePosition(document, { x: x / length * distance, y: y / length * distance, z: z / length * distance });
  });
};

const createCustomMemoryGalaxyLayer = (shimmerStrength = 1.35, particleDensity = 1) => {
  const count = Math.round(430000 * particleDensity);
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const sizeScales = new Float32Array(count);
  const shimmerPhases = new Float32Array(count);
  const palette = ['#78e6bd', '#8ad7ff', '#c7a0ff', '#ff9fc5', '#ffad73'].map((value) => new THREE.Color(value));
  let seed = 0x6d656d31;
  const random = () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let value = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
  const gaussianRandom = () => Math.sqrt(-2 * Math.log(Math.max(1e-7, random())))
    * Math.cos(Math.PI * 2 * random());
  for (let index = 0; index < count; index += 1) {
    const kind = random();
    const core = kind < 0.10;
    const bridge = !core && kind < 0.11;
    const haze = !core && !bridge && kind < 0.13;
    const outer = !core && !bridge && !haze && kind < 0.14;
    let radius;
    let angle;
    let x;
    let y;
    let z;
    let coreDistance = 0;
    let armIndex = 0;
    let armProgress = 1;
    if (core) {
      // 等轴高斯球核：任何观察角度都保持圆形，且外缘没有硬边界。
      x = gaussianRandom() * 34;
      y = gaussianRandom() * 34;
      radius = Math.sqrt(x * x + y * y);
      // 核心在 Z 轴上更饱满，侧视时仍能看到明确的球体高度。
      z = gaussianRandom() * 112;
      coreDistance = Math.sqrt(x * x + y * y + (z / 2.35) * (z / 2.35));
      angle = Math.atan2(y, x);
    } else if (bridge) {
      // 轻量核—臂过渡层，使球核的密度连续流入悬臂根部。
      const progress = Math.pow(random(), 1.9);
      radius = 28 + progress * 285;
      // 过渡层保持近球形，不再按五条悬臂分瓣，从根源上消除中心五角星轮廓。
      const azimuth = random() * Math.PI * 2;
      const polarCos = random() * 2 - 1;
      const polarSin = Math.sqrt(1 - polarCos * polarCos);
      armIndex = Math.floor(random() * palette.length);
      x = Math.cos(azimuth) * polarSin * radius;
      y = Math.sin(azimuth) * polarSin * radius;
      z = polarCos * radius * 0.88 + gaussianRandom() * 16;
      angle = azimuth;
    } else if (outer) {
      // 少量越过主盘面的低亮度粒子，打散最外层的规则圆形轮廓。
      radius = 525 - Math.log(Math.max(0.012, random())) * 132;
      angle = random() * Math.PI * 2;
      x = Math.cos(angle) * radius;
      y = Math.sin(angle) * radius * (0.88 + random() * 0.12);
      z = (random() - 0.5) * 140;
    } else {
      // 主悬臂使用更接近均匀的进度分布，避免粒子全挤在根部而尾部过淡。
      const progress = Math.pow(random(), haze ? 1.38 : 1.32);
      armProgress = progress;
      radius = haze ? (45 + progress * 610) : (78 + progress * 570);
      const armCount = 5;
      const arm = Math.floor(random() * armCount);
      armIndex = arm;
      const widthScale = [0.78, 1.14, 0.91, 1.22, 0.86][arm];
      const curveScale = [0.88, 1.09, 0.96, 1.15, 0.84][arm];
      const lengthScale = [0.91, 1.08, 0.86, 1.12, 0.97][arm];
      radius = haze
        ? (45 + progress * 610)
        : (48 + progress * 600 * lengthScale);
      // 保持宽厚悬臂：根部和中段有体积，外段继续柔和逸散。
      const spread = (0.52 + Math.sin(progress * Math.PI) * 0.20
        + progress * progress * 0.28) * widthScale;
      const branch = !haze && progress > 0.45 && random() > 0.7
        ? (random() > 0.5 ? 1 : -1) * (0.07 + progress * 0.18)
        : 0;
      const irregularity = Math.sin(progress * (6.4 + arm * 0.61) + arm * 1.7) * (0.075 + arm * 0.007)
        + Math.sin(progress * (13.2 + arm * 0.46) + arm * 0.83) * 0.042;
      const armAngle = arm * Math.PI * 2 / armCount
        + progress * 1.48 * curveScale + irregularity + branch;
      // 盘面尘埃使用自由角度填补悬臂之间的暗缝；悬臂用近似高斯的
      // 横向散布形成“中间亮、边缘逐渐逸散”的柔边，而不是清晰色带。
      let gaussian = (random() + random() + random() - 1.5) / 1.5;
      if (haze) {
        angle = random() * Math.PI * 2;
      } else {
        // 大部分粒子聚成可辨识的主脊，剩余粒子保留原有宽阔柔边。
        gaussian *= random() < 0.68 ? 0.64 : 1.12;
        // 主悬臂在核心内部先融入圆形星云，离开内圈后才平滑显出五条方向。
        const diffuseAngle = random() * Math.PI * 2;
        const rawAlignment = Math.max(0, Math.min(1, (progress - 0.035) / 0.2));
        const alignment = rawAlignment * rawAlignment * (3 - 2 * rawAlignment);
        const angleDelta = Math.atan2(
          Math.sin(armAngle - diffuseAngle), Math.cos(armAngle - diffuseAngle),
        );
        angle = diffuseAngle + angleDelta * alignment + gaussian * spread;
      }
      const radialScatter = (random() - 0.5) * (haze ? 92 : (46 + progress * 88));
      const actualRadius = radius + radialScatter;
      x = Math.cos(angle) * actualRadius;
      y = Math.sin(angle) * actualRadius * 0.94;
      const thickness = 138 - progress * 62;
      z = ((random() + random() + random() - 1.5) / 1.5) * thickness;
    }
    const offset = index * 3;
    positions[offset] = x + (random() - 0.5) * 14;
    positions[offset + 1] = y + (random() - 0.5) * 14;
    positions[offset + 2] = z;
    const color = core
      ? new THREE.Color().setHSL(
        0.12,
        0.08,
        0.2 + Math.exp(-Math.pow(coreDistance / 25, 2)) * 0.6 + random() * 0.055,
      )
      : (bridge
        ? new THREE.Color('#747a78').lerp(palette[armIndex], 0.28 + random() * 0.34)
        : outer
        ? new THREE.Color('#526779').lerp(new THREE.Color('#a2869a'), random() * 0.38)
        : haze
        ? new THREE.Color('#667d91').lerp(new THREE.Color('#c7b9a8'), random() * 0.34)
        : palette[armIndex].clone().lerp(new THREE.Color('#ffffff'), 0.12 + random() * 0.2));
    // 球核之外不再使用完全一致的色带；在统一调色板内逐粒混色，保持协调但避免机械分区。
    if (!core) {
      color.lerp(palette[Math.floor(random() * palette.length)], 0.16 + random() * 0.34);
    }
    if (bridge) color.multiplyScalar(0.52);
    if (haze) color.multiplyScalar(0.76);
    if (!core && !bridge && !haze && !outer) {
      color.lerp(new THREE.Color('#ffffff'), 0.1 + (1 - armProgress) * 0.42);
      color.multiplyScalar(1.82 + (1 - armProgress) * 0.46);
    }
    colors[offset] = color.r; colors[offset + 1] = color.g; colors[offset + 2] = color.b;
    // 核外粒径全部在明确上下限内随机；悬臂根部略偏大以强化主脊和连接形状。
    const randomOuterSize = 0.78 + random() * 0.72;
    sizeScales[index] = core ? 0.92
      : ((!bridge && !haze && !outer)
        ? randomOuterSize * (1.04 + (1 - armProgress) * 0.16)
        : randomOuterSize);
    shimmerPhases[index] = (!core && !bridge && !haze && !outer) ? random() * Math.PI * 2 : -1;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geometry.setAttribute('sizeScale', new THREE.BufferAttribute(sizeScales, 1));
  geometry.setAttribute('shimmerPhase', new THREE.BufferAttribute(shimmerPhases, 1));
  const material = new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uSize: { value: 6.25 },
      uOpacity: { value: 0.88 },
      uShimmerStrength: { value: shimmerStrength },
    },
    vertexShader: `
      attribute vec3 color;
      attribute float shimmerPhase;
      attribute float sizeScale;
      varying vec3 vColor;
      varying float vShimmerPhase;
      uniform float uSize;
      void main() {
        vColor = color;
        vShimmerPhase = shimmerPhase;
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = clamp(uSize * sizeScale * (760.0 / max(1.0, -mvPosition.z)), 0.5, 56.0);
        gl_Position = projectionMatrix * mvPosition;
      }
    `,
    fragmentShader: `
      varying vec3 vColor;
      varying float vShimmerPhase;
      uniform float uTime;
      uniform float uOpacity;
      uniform float uShimmerStrength;
      void main() {
        float distanceToCenter = length(gl_PointCoord - vec2(0.5)) * 2.0;
        if (distanceToCenter > 1.0) discard;
        float softPoint = pow(1.0 - distanceToCenter, 1.65);
        float shimmer = 1.0;
        if (vShimmerPhase >= 0.0) {
          float slowWave = sin(uTime * 1.9 + vShimmerPhase);
          float fineWave = sin(uTime * 3.8 + vShimmerPhase * 1.73);
          float animatedLevel = 0.24 + 0.58 * slowWave + 0.3 * fineWave;
          shimmer = 1.0 + uShimmerStrength * (animatedLevel - 1.0);
          shimmer = clamp(shimmer, 0.002, 1.5);
        }
        gl_FragColor = vec4(vColor, softPoint * uOpacity * shimmer);
      }
    `,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  const layer = new THREE.Group();
  layer.name = MEMORY_GALAXY_VERSION;
  layer.rotation.x = MEMORY_GALAXY_TILT;
  layer.scale.setScalar(MEMORY_GALAXY_SCALE);
  layer.add(points);
  layer.userData.rotator = points;
  layer.userData.particleMaterial = material;
  layer.userData.dispose = () => {
    geometry.dispose();
    material.dispose();
  };
  return layer;
};

// Ported from Cohenjikan/shiyun, last MIT revision 928c79e (Galaxy.tsx).
// The original React Three Fiber component is expressed as a plain THREE.Group so it can live
// inside react-force-graph without changing KnowNexus's graph/data interaction layer.
const createShiyunMemoryGalaxyLayer = (particleDensity = 1) => {
  const R = 650;
  const BRANCHES = 4;
  const TWIST = 5.2;
  const ARM_SPREAD = 0.42;
  const THICKNESS = 0.11;
  const DUST = Math.round(80000 * particleDensity);
  const STARS = Math.round(7000 * particleDensity);
  // 低档位优先多削减一点中心球核，悬臂轮廓和整体尺度保持不变。
  const BULGE = Math.round(40000 * Math.pow(particleDensity, 1.18));
  const total = DUST + STARS + BULGE;
  let seed = 31337;
  const random = () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let value = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
  const gauss3 = () => random() + random() + random() - 1.5;
  const valueNoise = (x, y) => {
    const xi = Math.floor(x); const yi = Math.floor(y);
    const xf = x - xi; const yf = y - yi;
    const u = xf * xf * (3 - 2 * xf); const v = yf * yf * (3 - 2 * yf);
    const hash = (a, b) => {
      const n = Math.sin(a * 127.1 + b * 311.7) * 43758.5453;
      return n - Math.floor(n);
    };
    const n00 = hash(xi, yi); const n10 = hash(xi + 1, yi);
    const n01 = hash(xi, yi + 1); const n11 = hash(xi + 1, yi + 1);
    return (n00 * (1 - u) + n10 * u) * (1 - v)
      + (n01 * (1 - u) + n11 * u) * v;
  };
  const exponentialRadius = (h, cap) => Math.min(cap, -h * Math.log(1 - random() * 0.9999));
  const positions = new Float32Array(total * 3);
  const colors = new Float32Array(total * 3);
  const scales = new Float32Array(total);
  const phases = new Float32Array(total);
  const cCore = new THREE.Color('#fff1d6');
  const cInner = new THREE.Color('#fff7ec');
  const cMid = new THREE.Color('#ffffff');
  const cArm = new THREE.Color('#cfe0ff');
  const cHii = new THREE.Color('#ff6d92');
  const coreRimPalette = ['#82d9ff', '#8ff0c7', '#c4a0ff', '#ffb47d']
    .map((value) => new THREE.Color(value));
  const color = new THREE.Color();
  const noiseFrequency = 4.2 / R;

  for (let index = 0; index < total; index += 1) {
    const bulge = index >= DUST + STARS;
    const star = !bulge && index >= DUST;
    let x; let y; let z; let t; let armProximity = 0; let brightness; let hii = false;
    if (bulge) {
      const radius = exponentialRadius(R * 0.1, R * 0.42);
      t = radius / R;
      const phi = random() * Math.PI * 2;
      const cosTheta = 2 * random() - 1;
      const sinTheta = Math.sqrt(Math.max(0, 1 - cosTheta * cosTheta));
      x = radius * sinTheta * Math.cos(phi) + R * 0.05 * (random() - 0.5);
      z = radius * sinTheta * Math.sin(phi) + R * 0.05 * (random() - 0.5);
      y = radius * cosTheta * 0.6 + R * 0.03 * (random() - 0.5);
      armProximity = 0.2;
      const noise = valueNoise(x * noiseFrequency * 1.6, z * noiseFrequency * 1.6);
      brightness = (0.8 - t * 0.75) * (0.55 + random() * 0.5) * (0.7 + noise * 0.75);
    } else {
      const radius = exponentialRadius(R * 0.27, R) + R * 0.015;
      t = radius / R;
      const branch = Math.floor(random() * BRANCHES) / BRANCHES * Math.PI * 2;
      const armDeviation = gauss3() * ARM_SPREAD;
      armProximity = Math.exp(-((armDeviation / ARM_SPREAD) ** 2) * 2.2);
      const centerBlur = Math.max(0, 0.45 - t) / 0.45;
      const angle = branch + t * TWIST + armDeviation
        + (random() - 0.5) * Math.PI * 2 * centerBlur * centerBlur;
      const scatter = (amount) => Math.pow(random(), 2.6)
        * (random() < 0.5 ? -1 : 1) * amount * radius;
      const coreFill = centerBlur * centerBlur * R * 0.07;
      x = Math.cos(angle) * radius + scatter(0.16) + (random() - 0.5) * 2 * coreFill;
      z = Math.sin(angle) * radius + scatter(0.16) + (random() - 0.5) * 2 * coreFill;
      y = gauss3() * radius * THICKNESS * (star ? 0.8 : 1.1);
      const noise = valueNoise(x * noiseFrequency, z * noiseFrequency);
      const armBoost = star ? 0.42 + armProximity : 0.34 + armProximity * 0.75;
      brightness = (armBoost + centerBlur * 0.4)
        * (0.45 + centerBlur * 0.25 + noise * 0.8) * (0.8 + random() * 0.4);
      hii = star && armProximity > 0.55 && random() < 0.04;
    }
    const offset = index * 3;
    // Poetry Cloud uses X/Z as the disk and Y as height. KnowNexus's galaxy transform expects
    // X/Y as the disk and Z as height, so swap axes once here to keep backdrop and graph stars glued.
    positions[offset] = x; positions[offset + 1] = z; positions[offset + 2] = y;
    if (t < 0.12) color.copy(cCore).lerp(cInner, t / 0.12);
    else if (t < 0.4) color.copy(cInner).lerp(cMid, (t - 0.12) / 0.28);
    else color.copy(cMid).lerp(cArm, Math.min(1, (t - 0.4) / 0.5));
    // 球核外圈不再是统一白雾：用稳定随机冷/暖色和更大粒径差形成可辨识的过渡层。
    if (bulge && t > 0.1) {
      color.lerp(coreRimPalette[Math.floor(random() * coreRimPalette.length)], 0.18 + random() * 0.38);
    }
    if (!bulge) color.lerp(cArm, armProximity * 0.45);
    if (hii) color.copy(cHii);
    colors[offset] = color.r * brightness;
    colors[offset + 1] = color.g * brightness;
    colors[offset + 2] = color.b * brightness;
    scales[index] = bulge
      ? (1.35 + (0.3 - t) * 2.6) * (0.48 + random() * 1.18)
      : star
        ? (0.7 + armProximity * 0.8 + (hii ? 0.8 : 0)) * (0.7 + random() * 0.6)
        : (0.5 + (1 - t) * 0.8) * (0.7 + random() * 0.5);
    phases[index] = star ? random() * Math.PI * 2 : -1;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('aColor', new THREE.BufferAttribute(colors, 3));
  geometry.setAttribute('aScale', new THREE.BufferAttribute(scales, 1));
  geometry.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1));
  const material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: { uSize: { value: 3 }, uTime: { value: 0 }, uShimmerStrength: { value: 1.35 } },
    vertexShader: `
      uniform float uSize;
      attribute vec3 aColor; attribute float aScale; attribute float aPhase;
      varying vec3 vColor; varying float vPhase;
      void main() {
        vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * viewPosition;
        gl_PointSize = clamp(uSize * aScale * (900.0 / max(1.0, -viewPosition.z)), 0.6, 56.0);
        vColor = aColor; vPhase = aPhase;
      }`,
    fragmentShader: `
      uniform float uTime; uniform float uShimmerStrength;
      varying vec3 vColor; varying float vPhase;
      void main() {
        float distanceToCenter = length(gl_PointCoord - vec2(0.5)) * 2.0;
        float alpha = exp(-distanceToCenter * distanceToCenter * 4.5);
        if (alpha < 0.004) discard;
        float shimmer = vPhase < 0.0 ? 1.0
          : clamp(0.7 + sin(uTime * 1.9 + vPhase) * 0.3 * uShimmerStrength, 0.08, 1.7);
        gl_FragColor = vec4(vColor * alpha * shimmer, alpha);
      }`,
  });
  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;

  // Poetry Cloud's colourful visible body is its PoetStars layer, not Galaxy's pale dust alone.
  // Recreate the MIT layer at the original public count, using the same dynasty palette, radial
  // bands, four-arm skeleton, point shader and deterministic distribution (without poem data).
  const dynastyPalette = [
    '#2fd6cf', '#36d09a', '#49c06e', '#7cba52', '#a8b84a', '#ffd27a', '#ffac5a',
    '#6ee7a8', '#8fd0c0', '#b0c98a', '#b794f6', '#f6759a', '#ff8c5a', '#ff6f91', '#d96fb0',
  ].map((value) => new THREE.Color(value));
  const dynastyWeights = [0.3, 0.3, 0.5, 0.6, 0.2, 2.2, 0.4, 3, 0.1, 0.4, 1.3, 2.8, 2, 1, 0.9];
  const weightTotal = dynastyWeights.reduce((sum, value) => sum + value, 0);
  const poetCount = Math.round(22000 * particleDensity);
  const poetPositions = new Float32Array(poetCount * 3);
  const poetColors = new Float32Array(poetCount * 3);
  const poetSizes = new Float32Array(poetCount);
  const poetSeeds = new Float32Array(poetCount);
  for (let index = 0; index < poetCount; index += 1) {
    let ticket = random() * weightTotal;
    let dynasty = 0;
    while (dynasty < dynastyWeights.length - 1 && ticket > dynastyWeights[dynasty]) {
      ticket -= dynastyWeights[dynasty]; dynasty += 1;
    }
    const originalInner = 420 + dynasty * ((3400 - 420) / 15);
    const originalOuter = originalInner + ((3400 - 420) / 15);
    const center = ((originalInner + originalOuter) * 0.5) / 3600 * R;
    const width = (originalOuter - originalInner) / 3600 * R;
    const radius = Math.max(86, Math.min(3400 / 3600 * R * 1.06,
      center + gauss3() * width * 1.5));
    const progress = radius / R;
    const arm = index % BRANCHES;
    const armDeviation = gauss3() * ARM_SPREAD * 0.45;
    const centerBlur = Math.max(0, 0.5 - progress) / 0.5;
    const angle = arm / BRANCHES * Math.PI * 2 + progress * TWIST + armDeviation
      + (random() - 0.5) * Math.PI * 2 * centerBlur;
    const scatter = () => Math.pow(random(), 2.2) * (random() < 0.5 ? -1 : 1) * 0.22 * radius;
    const coreScatter = centerBlur * centerBlur * R * 0.22;
    const px = Math.cos(angle) * radius + scatter() + (random() - 0.5) * 2 * coreScatter;
    const py = Math.sin(angle) * radius + scatter() + (random() - 0.5) * 2 * coreScatter;
    const bulge = 1 + Math.max(0, 0.45 - progress) * 2.6;
    const pz = gauss3() * radius * THICKNESS * 2.1 * bulge;
    const offset = index * 3;
    poetPositions[offset] = px; poetPositions[offset + 1] = py; poetPositions[offset + 2] = pz;
    const poetColor = dynastyPalette[dynasty].clone().offsetHSL(
      (random() - 0.5) * 0.055,
      0.14 + random() * 0.12,
      (random() - 0.5) * 0.16,
    );
    poetColors[offset] = poetColor.r; poetColors[offset + 1] = poetColor.g; poetColors[offset + 2] = poetColor.b;
    const sizeClass = random();
    poetSizes[index] = sizeClass < 0.055
      ? 4.8 + random() * 6.2
      : sizeClass < 0.24
        ? 2.2 + random() * 3.4
        : 0.62 + Math.pow(random(), 1.7) * 1.75;
    poetSeeds[index] = random();
  }
  const poetGeometry = new THREE.BufferGeometry();
  poetGeometry.setAttribute('position', new THREE.BufferAttribute(poetPositions, 3));
  poetGeometry.setAttribute('aColor', new THREE.BufferAttribute(poetColors, 3));
  poetGeometry.setAttribute('aSize', new THREE.BufferAttribute(poetSizes, 1));
  poetGeometry.setAttribute('aSeed', new THREE.BufferAttribute(poetSeeds, 1));
  const poetMaterial = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uSizeScale: { value: 900 }, uShimmerStrength: { value: 1.35 } },
    vertexShader: `
      attribute vec3 aColor; attribute float aSize; attribute float aSeed;
      uniform float uTime; uniform float uSizeScale;
      varying vec3 vColor; varying float vTwinkle;
      void main() {
        vColor = aColor;
        vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = clamp(aSize * (uSizeScale / max(1.0, -viewPosition.z)), 1.2, 60.0);
        vTwinkle = 0.7 + 0.3 * sin(uTime * 0.7 + aSeed * 6.2831853);
        gl_Position = projectionMatrix * viewPosition;
      }`,
    fragmentShader: `
      varying vec3 vColor; varying float vTwinkle;
      void main() {
        float distanceToCenter = length(gl_PointCoord - vec2(0.5));
        float alpha = smoothstep(0.5, 0.03, distanceToCenter);
        if (alpha < 0.02) discard;
        gl_FragColor = vec4(vColor * 2.3, alpha * vTwinkle);
      }`,
  });
  const poetPoints = new THREE.Points(poetGeometry, poetMaterial);
  poetPoints.frustumCulled = false;

  const layer = new THREE.Group();
  layer.name = 'memory-galaxy-shiyun-mit';
  layer.rotation.x = MEMORY_GALAXY_TILT;
  layer.scale.setScalar(MEMORY_GALAXY_SCALE);
  const rotatingGroup = new THREE.Group();
  rotatingGroup.add(points, poetPoints);
  layer.add(rotatingGroup);
  layer.userData.rotator = rotatingGroup;
  layer.userData.particleMaterial = material;
  layer.userData.starMaterial = poetMaterial;
  layer.userData.dispose = () => {
    geometry.dispose(); material.dispose(); poetGeometry.dispose(); poetMaterial.dispose();
  };
  return layer;
};

const createMemoryGalaxyLayer = (style, shimmerStrength, particleDensity = 1) => {
  const layer = style === 'shiyun'
    ? createShiyunMemoryGalaxyLayer(particleDensity)
    : createCustomMemoryGalaxyLayer(shimmerStrength, particleDensity);
  if (layer.userData.particleMaterial?.uniforms?.uShimmerStrength) {
    layer.userData.particleMaterial.uniforms.uShimmerStrength.value = shimmerStrength;
  }
  return layer;
};

// 项目图谱不是“多个知识领域的星系”，而是一棵确定的包含树。
// 使用分层环形布局，让项目、目录、文件、代码块始终同时出现在镜头范围内。
const applyProjectTreeLayout = (nodes, nodeMap) => {
  const roots = nodes.filter((node) => node.original_node_type === 'project');
  const children = new Map();
  nodes.forEach((node) => {
    if (!node.parent) return;
    if (!children.has(node.parent)) children.set(node.parent, []);
    children.get(node.parent).push(node);
  });

  roots.forEach((root, rootIndex) => {
    const rootX = (rootIndex - (roots.length - 1) / 2) * 1900;
    const levels = [[root]];
    const visited = new Set([root.id]);
    let frontier = [root];
    while (frontier.length) {
      const next = [];
      frontier.forEach((parent) => {
        (children.get(parent.id) || []).forEach((child) => {
          if (!visited.has(child.id)) {
            visited.add(child.id);
            next.push(child);
          }
        });
      });
      if (next.length) levels.push(next);
      frontier = next;
    }

    levels.forEach((levelNodes, depth) => {
      if (depth === 0) {
        const node = levelNodes[0];
        node.fx = node.x = rootX;
        node.fy = node.y = 0;
        node.fz = node.z = 0;
        return;
      }
      const radius = 230 + depth * 210;
      levelNodes.forEach((node, index) => {
        const angle = (Math.PI * 2 * index) / Math.max(levelNodes.length, 1)
          + depth * 0.42;
        node.fx = node.x = rootX + Math.cos(angle) * radius;
        node.fy = node.y = Math.sin(angle) * radius;
        node.fz = node.z = (depth - 1) * 90 + ((index % 3) - 1) * 70;
      });
    });
  });

  // 防御异常孤儿节点：靠近对应父节点或原点，避免落到不可见位置。
  nodes.filter((node) => !Number.isFinite(node.x)).forEach((node, index) => {
    const parent = nodeMap.get(node.parent);
    node.fx = node.x = (parent?.x || 0) + ((index % 5) - 2) * 90;
    node.fy = node.y = (parent?.y || 0) + (Math.floor(index / 5) + 1) * 90;
    node.fz = node.z = parent?.z || 0;
  });
};

// ====================================================================
//  主组件（3D 力导向图谱）
// ====================================================================
function StarfieldApp({
  apiBase = '',
  graphEndpoint = '/api/graph/graph',
  title = 'KnowNexus 知识星图',
  simpleMode = false,
  directoryTitle = '知识目录',
  roadmapSelector = false,
  graphDomain = '',
  directoryMode = 'tree',
  freeScatter = false,
  memoryOriginSelector = false,
  onOpenLibraryDocument = null,
  onOpenLibraryNote = null,
  onOpenWikiPage = null,
}) {
  const fgRef = useRef();
  const memoryPointCloudRef = useRef(null);
  const graphContainerRef = useRef(null);
  const [graphSize, setGraphSize] = useState({ width: 0, height: 0 });
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [memoryExpanded, setMemoryExpanded] = useState(false);
  const [memoryClustered, setMemoryClustered] = useState(false);
  const [memoryWorkbenchOpen, setMemoryWorkbenchOpen] = useState(false);
  const [focusedMemoryId, setFocusedMemoryId] = useState('');
  const [focusRelationsVisible, setFocusRelationsVisible] = useState(false);
  const [focusOrigin, setFocusOrigin] = useState({ x: 0, y: 0, scale: .45, rotate: 0 });
  const memoryWorkbenchRef = useRef(null);
  const [memoryAgentFilter, setMemoryAgentFilter] = useState('all');
  const [memoryWorkbenchQuery, setMemoryWorkbenchQuery] = useState('');
  const [renderSettingsOpen, setRenderSettingsOpen] = useState(false);
  const [renderSettings, setRenderSettings] = useState(loadRenderSettings);
  const [renderSettingsDraft, setRenderSettingsDraft] = useState(loadRenderSettings);
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectionCardVisible, setSelectionCardVisible] = useState(true);
  const relationRevealRef = useRef(1);
  const relationRevealFrameRef = useRef(0);
  const [relationAnimationActive, setRelationAnimationActive] = useState(false);
  const [renamingSessionId, setRenamingSessionId] = useState('');
  const [sessionNameDraft, setSessionNameDraft] = useState('');
  const [hoveredNode, setHoveredNode] = useState(null);
  const [hoverCardPosition, setHoverCardPosition] = useState(null);
  const [pinnedCardPosition, setPinnedCardPosition] = useState(null);
  const [fileTree, setFileTree] = useState([]);
  const [sidebarVisible, setSidebarVisible] = useState(false); // 默认收起，让星图占满中间矩形块（用户要求）
  const [sidebarWidth, setSidebarWidth] = useState(() => Number(localStorage.getItem('personal-agent:memory-directory-width')) || 280);
  const [deleteSessionTarget, setDeleteSessionTarget] = useState(null);
  const [rememberDeleteChoice, setRememberDeleteChoice] = useState(false);
  useEffect(() => {
    setFocusRelationsVisible(false);
    if (!focusedMemoryId) return undefined;
    const timer = window.setTimeout(() => setFocusRelationsVisible(true), 720);
    return () => window.clearTimeout(timer);
  }, [focusedMemoryId]);
  useEffect(() => { localStorage.setItem('personal-agent:memory-directory-width', String(sidebarWidth)); }, [sidebarWidth]);
  const [loading, setLoading] = useState(true);
  const [graphError, setGraphError] = useState('');
  const [articleContent, setArticleContent] = useState(null);
  const [showArticle, setShowArticle] = useState(false);
  const [articleLoading, setArticleLoading] = useState(false); // 文章拉取中占位（按钮显示“加载中”）
  const [expandedDomains, setExpandedDomains] = useState({});
  const [filter, setFilter] = useState('all');
  const [noteSearchQuery, setNoteSearchQuery] = useState('');
  const [noteSearchOpen, setNoteSearchOpen] = useState(false);
  const [memorySearchQuery, setMemorySearchQuery] = useState('');
  const [memorySearchOpen, setMemorySearchOpen] = useState(false);
  const [viewMode, setViewMode] = useState('galaxy'); // 默认总览（单球），clusters(分域多球) | galaxy(单球总览)
  const [roadmapOptions, setRoadmapOptions] = useState([]);
  const [selectedRoadmapId, setSelectedRoadmapId] = useState('');
  const [memoryOrigin] = useState('all');
  const [memoryClientFilter, setMemoryClientFilter] = useState('all');
  const [watcherStatus, setWatcherStatus] = useState(null);
  const [watcherError, setWatcherError] = useState('');
  const [watcherMenuOpen, setWatcherMenuOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyClient, setHistoryClient] = useState('');
  const [historySessions, setHistorySessions] = useState([]);
  const [historySelectedSession, setHistorySelectedSession] = useState(null);
  const [historyPreview, setHistoryPreview] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyMessage, setHistoryMessage] = useState('');
  const [graphRefreshKey, setGraphRefreshKey] = useState(0);
  const historyRequestRef = useRef(0);
  const sessionRenameInFlightRef = useRef('');
  const nodeMapRef = useRef(null);     // 缓存 节点id→节点 映射，供切换布局时计算目标坐标
  const graphDataRef = useRef({ nodes: [], links: [] });  // 缓存图谱数据
  const galaxyLayerRef = useRef(null);
  const galaxyRotationRef = useRef(0);
  const galaxyTransitionUntilRef = useRef(0);
  const loadedProjectNodesRef = useRef(new Set()); // 记录已按需展开的项目节点
  const isTransitioning = useRef(false); // 切换布局 tween 进行中锁，避免动画期间重复触发

  useEffect(() => {
    if (!roadmapSelector) return undefined;
    let cancelled = false;
    fetch(`${apiBase}/api/plan/roadmap/personal`)
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.message || data.detail || '学习路线列表加载失败');
        return data;
      })
      .then((data) => {
        if (cancelled) return;
        setRoadmapOptions(data.plans || []);
        const current = (data.plans || []).find((plan) => plan.is_current) || data.plan;
        setSelectedRoadmapId(current?.id ? String(current.id) : '');
      })
      .catch((error) => {
        if (!cancelled) setGraphError(error.message || '学习路线列表加载失败');
      });
    return () => { cancelled = true; };
  }, [apiBase, roadmapSelector]);

  const resolvedGraphEndpoint = roadmapSelector && selectedRoadmapId
    ? `${graphEndpoint}?roadmap_id=${encodeURIComponent(selectedRoadmapId)}`
    : graphEndpoint;

  const refreshWatcherStatus = useCallback(async () => {
    if (!memoryOriginSelector) return;
    try {
      const response = await fetch(`${apiBase}/api/integrations/codex-watcher`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || '监听状态获取失败');
      setWatcherStatus(data);
      setWatcherError(data.last_error || '');
    } catch (error) {
      setWatcherError(error.message || '监听状态获取失败');
    }
  }, [apiBase, memoryOriginSelector]);

  useEffect(() => {
    if (!memoryOriginSelector) return undefined;
    refreshWatcherStatus();
    const timer = window.setInterval(refreshWatcherStatus, 10000);
    return () => window.clearInterval(timer);
  }, [memoryOriginSelector, refreshWatcherStatus]);

  useEffect(() => {
    setMemoryClientFilter('all');
  }, [memoryOrigin]);

  const loadHistorySessions = useCallback(async (client = historyClient) => {
    if (!client) return;
    const requestId = historyRequestRef.current + 1;
    historyRequestRef.current = requestId;
    setHistoryLoading(true);
    setHistoryMessage('');
    try {
      const response = await fetch(`${apiBase}/api/integrations/conversation-history/sessions?client=${client}&limit=30`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || '历史会话查询失败');
      if (historyRequestRef.current === requestId) {
        setHistorySessions(data.sessions || []);
        setHistorySelectedSession(null);
        setHistoryPreview(null);
      }
    } catch (error) {
      if (historyRequestRef.current === requestId) {
        setHistorySessions([]);
        setHistoryMessage(error.message || '历史会话查询失败');
      }
    } finally {
      if (historyRequestRef.current === requestId) setHistoryLoading(false);
    }
  }, [apiBase, historyClient]);

  const previewHistorySession = async () => {
    if (!historySelectedSession) return;
    setHistoryLoading(true);
    setHistoryMessage('正在查询最近 20 轮对话…');
    try {
      const response = await fetch(`${apiBase}/api/integrations/conversation-history/preview?limit=20`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client: historySelectedSession.client, session_id: historySelectedSession.session_id }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || '会话内容查询失败');
      setHistoryPreview(data);
      setHistoryMessage(data.turn_count > data.shown_count
        ? `共 ${data.turn_count} 轮，当前展示最近 ${data.shown_count} 轮。`
        : `共 ${data.turn_count} 轮。`);
    } catch (error) {
      setHistoryPreview(null);
      setHistoryMessage(error.message || '会话内容查询失败');
    } finally {
      setHistoryLoading(false);
    }
  };

  const importHistorySession = async (session) => {
    setHistoryLoading(true);
    setHistoryMessage('正在导入所选会话…');
    try {
      const response = await fetch(`${apiBase}/api/integrations/conversation-history/import`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client: session.client, session_id: session.session_id }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || '历史会话导入失败');
      setHistoryMessage(`导入完成：新增 ${data.imported} 轮，已存在 ${data.duplicates} 轮。`);
      setGraphRefreshKey((value) => value + 1);
    } catch (error) {
      setHistoryMessage(error.message || '历史会话导入失败');
    } finally {
      setHistoryLoading(false);
    }
  };

  // ForceGraph3D 默认使用浏览器视口尺寸。当前页面右侧还有 AI 面板，
  // 如果不显式传入中间画布的尺寸，图谱中心会落在被裁切画布的右侧。
  useEffect(() => {
    const container = graphContainerRef.current;
    if (!container) return undefined;

    const updateGraphSize = () => {
      const { width, height } = container.getBoundingClientRect();
      setGraphSize(prev => {
        const nextWidth = Math.round(width);
        const nextHeight = Math.round(height);
        return prev.width === nextWidth && prev.height === nextHeight
          ? prev
          : { width: nextWidth, height: nextHeight };
      });
    };

    updateGraphSize();
    const resizeObserver = new ResizeObserver(updateGraphSize);
    resizeObserver.observe(container);
    return () => resizeObserver.disconnect();
  }, [loading]);

  // ===== 获取图谱数据 =====
  useEffect(() => {
    setLoading(true);
    setGraphError('');
    fetch(`${apiBase}${resolvedGraphEndpoint}`)
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.message || data.detail || `图谱请求失败（${res.status}）`);
        return data;
      })
      .then(data => {
        const domainGraph = data.nodes
          ? data
          : (graphDomain ? (data[`${graphDomain}_graph`] || {}) : data);
        const rawNodes = domainGraph.nodes || [];
        const rawEdges = domainGraph.edges || domainGraph.links || [];
        const typeMap = {
          project: 'domain', module: 'chapter', file: 'theory', block: 'tech',
          class: 'chapter', function: 'tech', method: 'tech',
          note: 'chapter', document: 'chapter', knowledge_point: 'theory',
          wiki_topic: 'domain', wiki_concept: 'theory', wiki_synthesis: 'tech', wiki_source: 'chapter',
          memory_point: 'theory', memory_entity: 'domain', conversation_turn: 'chapter',
        };
        let visibleRawNodes = graphDomain === 'note'
          ? rawNodes.filter((raw) => (raw.data || raw).node_type !== 'knowledge_point')
          : rawNodes;
        if (graphDomain === 'memory') {
          const visibleMemoryIds = new Set(rawNodes
            .filter((node) => ['memory_point', 'conversation_turn'].includes(node.node_type)
              && (memoryOrigin === 'all' || (node.payload?.origin_type || 'internal') === memoryOrigin))
            .map((node) => node.id));
          const connectedMemoryNodeIds = new Set();
          rawEdges.forEach((raw) => {
            const edge = raw.data || raw;
            if (visibleMemoryIds.has(edge.source)) connectedMemoryNodeIds.add(edge.target);
            if (visibleMemoryIds.has(edge.target)) connectedMemoryNodeIds.add(edge.source);
          });
          visibleRawNodes = rawNodes.filter((node) =>
            visibleMemoryIds.has(node.id) || connectedMemoryNodeIds.has(node.id));
        }
        const visibleIds = new Set(visibleRawNodes.map((raw) => (raw.data || raw).id));
        const parentById = new Map();
        rawEdges.forEach((raw) => {
          const edge = raw.data || raw;
          const relation = edge.label || edge.edge_type;
          // Wiki 主题是概念的真正布局父级。原文 contains 边只作为没有主题时的回退，
          // 避免多个概念被同一份原文拉到完全相同的位置。
          if (relation === 'groups') parentById.set(edge.target, edge.source);
          if (relation === 'contains' && !parentById.has(edge.target)) {
            parentById.set(edge.target, edge.source);
          }
          if (graphDomain === 'memory' && relation === 'ABOUT') {
            parentById.set(edge.source, edge.target);
          }
          if (graphDomain === 'memory' && relation === 'DERIVED_FROM') {
            parentById.set(edge.source, edge.target);
          }
        });
        const nodes = visibleRawNodes.map((raw) => {
          const node = raw.data || raw;
          const originalType = node.node_type || 'theory';
          const payload = node.payload || {};
          const readable = (
            (graphDomain === 'note' && originalType === 'note' && payload.filename)
            || (graphDomain === 'project' && payload.project_id && payload.file_path)
            || (graphDomain === 'memory' && (payload.memory_id || payload.turn_id))
          );
          return {
            ...node,
            payload,
            original_node_type: originalType,
            node_type: typeMap[originalType] || 'theory',
            description: node.description || node.summary || '',
            parent: node.parent || parentById.get(node.id) || null,
            article_path: readable ? `domain://${graphDomain}/${node.id}` : node.article_path,
            __rawLinks: [],
          };
        });
        const links = rawEdges.map((raw) => {
          const edge = raw.data || raw;
          return {
            source: edge.source,
            target: edge.target,
            edge_type: edge.edge_type || edge.label || 'related',
            label: edge.label,
            weight: edge.weight,
            payload: edge.payload || {},
          };
        }).filter((link) => visibleIds.has(link.source) && visibleIds.has(link.target));
        if (!nodes.length) {
          setGraphError(data.analysis || '暂无可展示的子图数据。');
        }

        const nodeMap = new Map(nodes.map(n => [n.id, n]));
        links.forEach(l => {
          const s = typeof l.source === 'object' ? l.source.id : l.source;
          const t = typeof l.target === 'object' ? l.target.id : l.target;
          if (nodeMap.has(s)) nodeMap.get(s).__rawLinks.push(t);
          if (nodeMap.has(t)) nodeMap.get(t).__rawLinks.push(s);
        });

        const tree = buildFileTree(nodes);
        setFileTree(tree);

        // 记忆目录默认展开客户端层，直接显示第二级会话 ID；会话下的对话仍可按需展开。
        setExpandedDomains(graphDomain === 'memory'
          ? Object.fromEntries(tree.map((item) => [item.id, true]))
          : {});

        // ===== 布局：分域(默认) 或 单球(总览) =====
        // 逻辑已抽至模块级 applyLayout(nodes, mode, nodeMap)；clusters 分支与原有完全一致。
        nodeMapRef.current = nodeMap;
        graphDataRef.current = { nodes, links };
        loadedProjectNodesRef.current = new Set();
        if (freeScatter || (graphDomain === 'memory' && renderSettings.memorySpatialLayout !== 'sphere')) {
          const spatialExtent = getMemorySpatialExtent(nodes.length, renderSettings.memorySpatialScale);
          nodes.forEach((node) => {
            const px = stableUnit(node.id, 701) * 2 - 1;
            const py = stableUnit(node.id, 709) * 2 - 1;
            const pz = stableUnit(node.id, 719) * 2 - 1;
            const positionLength = Math.hypot(px, py, pz) || 1;
            const spatialRadius = spatialExtent / 2;
            const radialDistance = Math.cbrt(stableUnit(node.id, 723)) * spatialRadius;
            node.fx = node.x = px / positionLength * radialDistance;
            node.fy = node.y = py / positionLength * radialDistance;
            node.fz = node.z = pz / positionLength * radialDistance;
            const dx = stableUnit(node.id, 727) * 2 - 1;
            const dy = stableUnit(node.id, 733) * 2 - 1;
            const dz = stableUnit(node.id, 739) * 2 - 1;
            const length = Math.hypot(dx, dy, dz) || 1;
            const speed = (2 + stableUnit(node.id, 743) * 4.2) * 5;
            node.__scatterVelocity = { x: dx / length * speed, y: dy / length * speed, z: dz / length * speed };
            node.__scatterRadius = spatialRadius;
          });
        } else if (graphDomain === 'project') {
          applyProjectTreeLayout(nodes, nodeMap);
        } else {
          applyLayout(nodes, viewMode, nodeMap);
        }

        nodes.forEach((node) => {
          node.__baseX = Number.isFinite(node.x) ? node.x : 0;
          node.__baseY = Number.isFinite(node.y) ? node.y : 0;
          node.__baseZ = Number.isFinite(node.z) ? node.z : 0;
        });
        applyPersonalizedLayout(nodes, renderSettings);
        if (graphDomain === 'note') applyNoteSemanticLayout(nodes, links);
        if (graphDomain === 'memory') {
          nodes.forEach((node, index) => {
            node.__relationPosition = { x: node.x || 0, y: node.y || 0, z: node.z || 0 };
            if (node.original_node_type === 'conversation_turn') {
              node.__galaxyPosition = galaxyPositionForStyle(
                node, index, renderSettings.memoryGalaxyStyle,
              );
              if (!memoryExpanded && renderSettings.memoryGalaxyEnabled) {
                setNodePosition(node, transformMemoryGalaxyPosition(
                  node.__galaxyPosition, galaxyRotationRef.current,
                ));
              }
            }
          });
        }

        setGraphData({ nodes, links });

        // 触发一次 resize 让 FG3D 重新测量容器尺寸
        setTimeout(() => {
          try { window.dispatchEvent(new Event('resize')); } catch(e) {}
        }, 300);
      })
      .catch((err) => {
        console.error('获取图谱数据失败:', err);
        setGraphError(err.message || '知识图谱加载失败，请确认后端已启动。');
      })
      .finally(() => setLoading(false));
  }, [apiBase, resolvedGraphEndpoint, simpleMode, graphDomain, memoryOrigin, freeScatter, graphRefreshKey]);

  // ===== 构建真实目录树（按 parent 递归，使用节点自带 icon）=====
  const buildFileTree = (nodes) => {
    if (directoryMode === 'notes') {
      return nodes
        .filter((node) => node.original_node_type === 'note')
        .sort((left, right) => {
          const leftTime = new Date(left.payload?.created_at || 0).valueOf() || 0;
          const rightTime = new Date(right.payload?.created_at || 0).valueOf() || 0;
          return rightTime - leftTime;
        })
        .map((node) => ({ ...node, icon: '📄', children: [] }));
    }
    if (graphDomain === 'memory') {
      const clients = new Map();
      nodes.filter((node) => node.original_node_type === 'conversation_turn')
        .sort((a, b) => new Date(b.payload?.created_at || 0) - new Date(a.payload?.created_at || 0))
        .forEach((node) => {
          const client = node.payload?.origin_client || 'personal_agent';
          const sessionId = node.payload?.session_id || 'unknown-session';
          if (!clients.has(client)) clients.set(client, new Map());
          const sessions = clients.get(client);
          if (!sessions.has(sessionId)) sessions.set(sessionId, []);
          sessions.get(sessionId).push({
            ...node,
            node_type: 'theory',
            icon: '✦',
            children: [],
          });
        });
      return [...clients.entries()].map(([client, sessions]) => ({
        id: `memory-client:${client}`,
        client,
        isSourceFilter: true,
        label: ({ codex: 'Codex', workbuddy: 'WorkBuddy', dsh: 'DeepSeek Harness', trae: 'Trae', claude_code: 'Claude Code', personal_agent: '内部记忆' })[client] || client,
        node_type: 'domain',
        icon: '◈',
        children: [...sessions.entries()].map(([sessionId, turns]) => {
          const storedTitle = turns[0]?.payload?.title || '';
          const sessionTitle = (!storedTitle || /^Codex\s+[0-9a-f-]+$/i.test(storedTitle))
            ? (turns[turns.length - 1]?.label || '未命名会话')
            : storedTitle;
          return ({
          id: `memory-session:${client}:${sessionId}`,
          sessionId,
          client,
          label: sessionTitle,
          title: sessionTitle,
          node_type: 'chapter',
          icon: '◇',
          children: turns,
          distillationStatus: turns.every((turn) => turn.payload?.distillation_status === 'distilled')
            ? 'distilled'
            : (turns.some((turn) => turn.payload?.distillation_status === 'processing') ? 'processing' : 'pending'),
        });}),
      }));
    }
    const childrenMap = new Map();
    // 按 parent 字段分组
    nodes.forEach(n => {
      const parentId = n.parent || '__root__';
      if (!childrenMap.has(parentId)) childrenMap.set(parentId, []);
      childrenMap.get(parentId).push(n);
    });
    // 按 sort_order 排序
    childrenMap.forEach(arr => arr.sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0)));

    // 递归构建
    const buildChildren = (parentId) => {
      const children = childrenMap.get(parentId) || [];
      return children.map(child => ({
        ...child,
        icon: child.icon || ICONS[child.node_type] || '📄',
        children: buildChildren(child.id),
      }));
    };

    // 顶层节点（parent 为空或不在节点表中的）按 domain 聚合
    const nodeIds = new Set(nodes.map(n => n.id));
    const topLevels = nodes.filter(n => !n.parent || !nodeIds.has(n.parent));
    // 已经有 parent 指向 domain 节点的，直接作为根
    if (simpleMode) {
      return topLevels.map(n => ({
        ...n,
        icon: n.icon || ICONS[n.node_type] || '📄',
        children: buildChildren(n.id),
      }));
    }
    const domains = topLevels.filter(n => n.node_type === 'domain');
    if (domains.length > 0) {
      return domains.map(d => ({
        ...d,
        icon: d.icon || '📁',
        children: buildChildren(d.id),
      }));
    }
    // 兜底：按 domain 分组
    const domainGroups = {};
    topLevels.forEach(n => {
      const domain = n.domain || '未分类';
      if (!domainGroups[domain]) domainGroups[domain] = [];
      domainGroups[domain].push(n);
    });
    return Object.entries(domainGroups).map(([domain, items]) => ({
      id: domain,
      label: domain,
      node_type: 'domain',
      icon: '📁',
      children: items.map(n => ({
        ...n,
        icon: n.icon || ICONS[n.node_type] || '📄',
        children: buildChildren(n.id),
      })),
    }));
  };

  // ===== 过滤数据 =====
  const filteredData = useMemo(() => {
    if (filter === 'all') return graphData;
    if (filter === 'contains') {
      const containsLinks = graphData.links.filter(l => l.edge_type === 'contains');
      const nodeIds = new Set();
      containsLinks.forEach(l => {
        nodeIds.add(typeof l.source === 'object' ? l.source.id : l.source);
        nodeIds.add(typeof l.target === 'object' ? l.target.id : l.target);
      });
      return { nodes: graphData.nodes.filter(n => nodeIds.has(n.id)), links: containsLinks };
    }
    if (filter === 'related') {
      const relatedLinks = graphData.links.filter(l => l.edge_type !== 'contains');
      const nodeIds = new Set();
      relatedLinks.forEach(l => {
        nodeIds.add(typeof l.source === 'object' ? l.source.id : l.source);
        nodeIds.add(typeof l.target === 'object' ? l.target.id : l.target);
      });
      return { nodes: graphData.nodes.filter(n => nodeIds.has(n.id)), links: relatedLinks };
    }
    return graphData;
  }, [graphData, filter]);

  const displayedGraphData = useMemo(() => {
    if (graphDomain !== 'memory') return filteredData;
    const sourceNodes = memoryClientFilter === 'all'
      ? filteredData.nodes
      : filteredData.nodes.filter(
        (node) => (node.payload?.origin_client || 'personal_agent') === memoryClientFilter,
      );
    if (memoryExpanded) {
      const expandedNodes = memoryClustered
        ? sourceNodes.filter((node) => ['memory_point', 'memory_entity'].includes(node.original_node_type))
        : sourceNodes;
      const sourceIds = new Set(expandedNodes.map((node) => node.id));
      return {
        nodes: expandedNodes,
        links: filteredData.links.filter((link) => {
          const source = typeof link.source === 'object' ? link.source.id : link.source;
          const target = typeof link.target === 'object' ? link.target.id : link.target;
          return sourceIds.has(source) && sourceIds.has(target);
        }),
      };
    }
    return {
      nodes: sourceNodes.filter((node) => node.original_node_type === 'conversation_turn'),
      links: [],
    };
  }, [filteredData, graphDomain, memoryExpanded, memoryClustered, memoryClientFilter]);

  // 集群默认只向渲染器提交节点。关系仍保留在 displayedGraphData 中用于连通分量布局，
  // 用户显式开启后才创建线对象，避免“透明但仍参与更新”的隐藏性能开销。
  const renderedGraphData = useMemo(() => {
    if (graphDomain !== 'memory' || !memoryClustered || renderSettings.memoryClusterShowLinks) {
      return displayedGraphData;
    }
    if (!selectedNode) return { nodes: displayedGraphData.nodes, links: [] };
    const selectedId = selectedNode.id;
    return {
      nodes: displayedGraphData.nodes,
      links: displayedGraphData.links.filter((link) => {
        const source = typeof link.source === 'object' ? link.source.id : link.source;
        const target = typeof link.target === 'object' ? link.target.id : link.target;
        return source === selectedId || target === selectedId;
      }),
    };
  }, [displayedGraphData, graphDomain, memoryClustered,
    renderSettings.memoryClusterShowLinks, selectedNode]);

  const wasMemoryClusteredRef = useRef(false);
  useEffect(() => {
    if (graphDomain !== 'memory') return;
    if (memoryClustered) {
      applyMemoryClusterLayout(
        displayedGraphData.nodes,
        displayedGraphData.links,
        renderSettings.memoryClusterSpatialScale,
      );
      wasMemoryClusteredRef.current = true;
      fgRef.current?.refresh?.();
      return;
    }
    if (wasMemoryClusteredRef.current) {
      graphDataRef.current.nodes.forEach((node) => {
        if (node.__relationPosition) setNodePosition(node, node.__relationPosition);
      });
      wasMemoryClusteredRef.current = false;
      fgRef.current?.refresh?.();
    }
  }, [displayedGraphData, graphDomain, memoryClustered, renderSettings.memoryClusterSpatialScale]);

  // ===== 选中节点关联 ID =====
  const connectedIds = useMemo(() => {
    if (!selectedNode) return new Set();
    const ids = new Set([selectedNode.id]);
    displayedGraphData.links.forEach(l => {
      const s = typeof l.source === 'object' ? l.source.id : l.source;
      const t = typeof l.target === 'object' ? l.target.id : l.target;
      if (s === selectedNode.id) ids.add(t);
      if (t === selectedNode.id) ids.add(s);
    });
    return ids;
  }, [selectedNode, displayedGraphData.links]);

  // 高连接节点仍完整展示节点与关系线，只限制常驻标签，避免文字完全覆盖图谱。
  const persistentLabelIds = useMemo(() => {
    if (!selectedNode) return new Set();
    if (connectedIds.size <= 24) return new Set(connectedIds);
    const degree = new Map();
    displayedGraphData.links.forEach((link) => {
      const source = typeof link.source === 'object' ? link.source.id : link.source;
      const target = typeof link.target === 'object' ? link.target.id : link.target;
      degree.set(source, (degree.get(source) || 0) + 1);
      degree.set(target, (degree.get(target) || 0) + 1);
    });
    const nodeById = new Map(displayedGraphData.nodes.map((node) => [node.id, node]));
    const distance = (node) => Math.hypot(
      (node?.x || 0) - (selectedNode.x || 0),
      (node?.y || 0) - (selectedNode.y || 0),
      (node?.z || 0) - (selectedNode.z || 0),
    );
    const prioritized = [...connectedIds]
      .filter((id) => id !== selectedNode.id)
      .sort((left, right) => {
        const degreeDelta = (degree.get(right) || 0) - (degree.get(left) || 0);
        return degreeDelta || distance(nodeById.get(left)) - distance(nodeById.get(right));
      })
      .slice(0, 17);
    return new Set([selectedNode.id, ...prioritized]);
  }, [connectedIds, displayedGraphData.links, displayedGraphData.nodes, selectedNode]);

  // ===== 强制 Three.js WebGL canvas 透明，让背景图透出 =====
  useEffect(() => {
    if (!fgRef.current) return;
    const trySetupAlpha = () => {
      try {
        const renderer = fgRef.current.renderer();
        if (renderer && renderer.domElement) {
          const canvas = renderer.domElement;
          canvas.style.background = 'transparent';
          // 全部记忆同时绘制大量 Sprite；将其 DPR 限制为 1，避免高分屏像素填充成为瓶颈。
          renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, memoryExpanded ? 1 : 1.5));
          const gl = renderer.getContext();
          if (gl) {
            // 获取当前 clear color，保留 alpha = 0
            renderer.setClearColor(0x000000, 0);
          }
        }
      } catch (e) { /* renderer 可能尚未初始化 */ }
    };
    // 延迟尝试，等 renderer 初始化
    const t1 = setTimeout(trySetupAlpha, 200);
    const t2 = setTimeout(trySetupAlpha, 500);
    const t3 = setTimeout(trySetupAlpha, 1000);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
  }, [filteredData.nodes.length > 0, memoryExpanded]);

  const focusMemoryView = useCallback((expanded, duration = 850) => {
    const distance = memoryClustered
      ? Math.max(12400, Math.cbrt(Math.max(displayedGraphData.nodes.length, 1))
        * 3360 * renderSettings.memoryClusterSpatialScale)
      : expanded
      ? 9000 * renderSettings.memorySpatialScale
      : 3000;
    fgRef.current?.cameraPosition?.(
      { x: 0, y: 0, z: distance },
      { x: 0, y: 0, z: 0 },
      duration,
    );
  }, [displayedGraphData.nodes.length, memoryClustered, renderSettings.memorySpatialScale,
    renderSettings.memoryClusterSpatialScale]);

  useEffect(() => {
    if (graphDomain !== 'memory' || !displayedGraphData.nodes.length || graphSize.width <= 0) return undefined;
    const timer = window.setTimeout(() => focusMemoryView(memoryExpanded), 220);
    return () => window.clearTimeout(timer);
  }, [graphDomain, displayedGraphData.nodes.length, graphSize.width, memoryExpanded, memoryClustered,
    renderSettings.memorySpatialLayout, focusMemoryView]);

  // 默认记忆视图的银河粒子层。它是一个 GPU Points 对象，展开关联或选择
  // “经典散点”后会完整移除，不改变关系图本身的数据和渲染方式。
  useEffect(() => {
    const fg = fgRef.current;
    const shouldShow = graphDomain === 'memory'
      && !memoryExpanded
      && renderSettings.memoryGalaxyEnabled
      && displayedGraphData.nodes.length > 0
      && graphSize.width > 0;
    if (!fg) return undefined;
    let scene;
    try { scene = fg.scene(); } catch { return undefined; }
    if (!scene) return undefined;
    if (galaxyLayerRef.current) {
      scene.remove(galaxyLayerRef.current);
      galaxyLayerRef.current.userData.dispose?.();
      galaxyLayerRef.current = null;
    }
    if (!shouldShow) return undefined;
    const layer = createMemoryGalaxyLayer(
      renderSettings.memoryGalaxyStyle,
      renderSettings.memoryGalaxyShimmerStrength,
      renderSettings.memoryGalaxyParticleLevel,
    );
    layer.renderOrder = -1;
    layer.userData.rotator.rotation.z = galaxyRotationRef.current;
    galaxyLayerRef.current = layer;
    scene.add(layer);
    fg.refresh?.();
    return () => {
      scene.remove(layer);
      layer.userData.dispose?.();
      if (galaxyLayerRef.current === layer) galaxyLayerRef.current = null;
    };
  }, [graphDomain, memoryExpanded, renderSettings.memoryGalaxyEnabled,
    renderSettings.memoryGalaxyStyle,
    renderSettings.memoryGalaxyShimmerStrength, renderSettings.memoryGalaxyParticleLevel,
    displayedGraphData.nodes, graphSize.width, graphSize.height]);

  // 银河盘面固定倾角，只让粒子与真实记忆节点沿本地 Z 轴同向慢速公转。
  // 这样不会再因相机环绕而周期性变成一条侧视直线。
  useEffect(() => {
    const active = graphDomain === 'memory'
      && !memoryExpanded
      && renderSettings.memoryGalaxyEnabled
      && displayedGraphData.nodes.length > 0;
    if (!active) return undefined;
    let frameId;
    let previousAt = performance.now();
    let previousRenderAt = 0;
    const animateGalaxy = (now) => {
      if (now - previousRenderAt < 50) {
        frameId = requestAnimationFrame(animateGalaxy);
        return;
      }
      previousRenderAt = now;
      const delta = Math.min(50, now - previousAt);
      previousAt = now;
      if (galaxyLayerRef.current?.userData?.particleMaterial?.uniforms?.uTime) {
        galaxyLayerRef.current.userData.particleMaterial.uniforms.uTime.value = now * 0.001;
      }
      if (galaxyLayerRef.current?.userData?.starMaterial?.uniforms?.uTime) {
        galaxyLayerRef.current.userData.starMaterial.uniforms.uTime.value = now * 0.001;
      }
      if (now >= galaxyTransitionUntilRef.current && selectedNode == null && hoveredNode == null) {
        galaxyRotationRef.current += delta * MEMORY_GALAXY_ROTATION_SPEED
          * renderSettings.memoryGalaxyRotationSpeed;
        const angle = galaxyRotationRef.current;
        if (galaxyLayerRef.current?.userData?.rotator) {
          galaxyLayerRef.current.userData.rotator.rotation.z = angle;
        }
        displayedGraphData.nodes.forEach((node) => {
          if (node.__galaxyPosition) {
            setNodePosition(node, transformMemoryGalaxyPosition(node.__galaxyPosition, angle));
          }
        });
        fgRef.current?.refresh?.();
      }
      frameId = requestAnimationFrame(animateGalaxy);
    };
    frameId = requestAnimationFrame(animateGalaxy);
    return () => cancelAnimationFrame(frameId);
  }, [graphDomain, memoryExpanded, renderSettings.memoryGalaxyEnabled,
    renderSettings.memorySpatialLayout,
    renderSettings.memoryGalaxyRotationSpeed,
    displayedGraphData.nodes, selectedNode, hoveredNode]);

  // ===== 辅助：相机对准所有节点的包围盒中心（= 真实视觉中心）=====
  // 关键修正：之前用 camera.lookAt(0,0,0) 对 5 领域布局（如三角双锥）会偏右。
  // ===== 3D 力配置（让外轮廓呈球形：子树从三锚点向四周铺满球体）=====
  useEffect(() => {
    if (!fgRef.current || filteredData.nodes.length === 0) return;

    if (freeScatter || (graphDomain === 'memory' && renderSettings.memorySpatialLayout !== 'sphere')) {
      // 记忆图谱始终使用大尺度自由空间，不再施加球面边界约束。
      fgRef.current.d3Force('sphere', null);
      const chargeForce = fgRef.current.d3Force('charge');
      if (chargeForce) chargeForce.strength(0);
      return;
    }

    // contains 构成项目树，imports 是跨模块的定向依赖边。
    fgRef.current.d3Force('link').distance((link) => {
      if (link.edge_type === 'contains') return 420;
      if (link.edge_type === 'imports') return 500;
      return 550;
    });

    // 排斥力减弱：让同簇内节点不会过度排斥、能自然散开填空间
    const chargeForce = fgRef.current.d3Force('charge');
    if (chargeForce) {
      chargeForce.strength(-40);
      chargeForce.distanceMax(1800);
    }

    // 球形边界约束（不可见）：所有非固定节点被收在球体内
    // 恢复力把超界节点推回，配合大连线距离让整体轮廓近似球体
    fgRef.current.d3Force('sphere', (alpha) => {
      const nodes = filteredData.nodes;
      for (const node of nodes) {
        if (node.fx != null) continue;
        const x = node.x || 0, y = node.y || 0, z = node.z || 0;
        const dist = Math.sqrt(x * x + y * y * 1.8 + z * z); // y 方向稍压缩适配视角
        if (dist > SPHERE_RADIUS) {
          const k = alpha * 0.12 * ((dist - SPHERE_RADIUS) / SPHERE_RADIUS);
          const nx = x / dist, ny = y / dist, nz = z / dist;
          node.vx -= k * nx * dist * 50;
          node.vy -= k * ny * dist * 50;
          node.vz -= k * nz * dist * 50;
        }
      }
    });
  }, [filteredData, freeScatter, graphDomain, renderSettings.memorySpatialLayout]);

  // ===== 关系图由相机慢速环绕；默认记忆银河改为盘面自身旋转 =====
  useEffect(() => {
    if (!fgRef.current || graphSize.width === 0 || filteredData.nodes.length === 0) return;
    try {
      const controls = fgRef.current.controls();
      const isCollapsedGalaxy = graphDomain === 'memory'
        && !memoryExpanded
        && renderSettings.memoryGalaxyEnabled;
      const independentMemoryScatter = graphDomain === 'memory'
        && renderSettings.memorySpatialLayout !== 'sphere';
      controls.autoRotate = !independentMemoryScatter && !isCollapsedGalaxy
        && selectedNode == null && hoveredNode == null;
      controls.autoRotateSpeed = 0.35;
    } catch (err) {
      console.warn('自动旋转初始化失败:', err);
    }
  }, [selectedNode, hoveredNode, graphSize.width, graphSize.height, filteredData.nodes.length,
    graphDomain, memoryExpanded, renderSettings.memoryGalaxyEnabled,
    renderSettings.memorySpatialLayout]);

  // 大空间散点：每颗星沿独立的随机三维向量缓慢漂移，到达边界后从另一侧回到空间。
  useEffect(() => {
    if (graphDomain !== 'memory' || !memoryExpanded || memoryClustered || selectedNode || renderSettings.memorySpatialLayout === 'sphere') return undefined;
    let frameId = 0;
    let previousAt = performance.now();
    let accumulator = 0;
    const animate = (now) => {
      const delta = Math.min(50, now - previousAt);
      previousAt = now;
      accumulator += delta;
      if (document.hidden) {
        accumulator = 0;
        frameId = window.requestAnimationFrame(animate);
        return;
      }
      if (accumulator >= 50) {
        const seconds = accumulator / 1000;
        accumulator = 0;
        graphDataRef.current.nodes.forEach((node) => {
          if (selectedNode?.id === node.id || connectedIds.has(node.id)) return;
          const velocity = node.__scatterVelocity;
          const radius = node.__scatterRadius;
          if (!velocity || !radius) return;
          const speedScale = renderSettings.memoryMovementSpeed;
          let x = (node.x || 0) + velocity.x * seconds * speedScale;
          let y = (node.y || 0) + velocity.y * seconds * speedScale;
          let z = (node.z || 0) + velocity.z * seconds * speedScale;
          const distance = Math.hypot(x, y, z);
          if (distance > radius) {
            const nx = x / distance;
            const ny = y / distance;
            const nz = z / distance;
            const dot = velocity.x * nx + velocity.y * ny + velocity.z * nz;
            velocity.x -= 2 * dot * nx;
            velocity.y -= 2 * dot * ny;
            velocity.z -= 2 * dot * nz;
            x = nx * radius;
            y = ny * radius;
            z = nz * radius;
          }
          setNodePosition(node, { x, y, z });
        });
        fgRef.current?.refresh?.();
      }
      frameId = window.requestAnimationFrame(animate);
    };
    frameId = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(frameId);
  }, [connectedIds, graphDomain, memoryExpanded, memoryClustered, renderSettings.memoryMovementSpeed,
    renderSettings.memorySpatialLayout, selectedNode]);

  // 记忆集群以各自球心为轴整体自转。节点和关系线共享同一组坐标更新，
  // 因而集群内部结构保持刚性，不会出现星点旋转而连线滞后的情况。
  useEffect(() => {
    if (graphDomain !== 'memory' || !memoryExpanded || !memoryClustered
      || renderSettings.memoryClusterShowLinks) return undefined;
    let frameId = 0;
    let lastFrame = 0;
    const startedAt = performance.now();
    const animateClusters = (now) => {
      if (!document.hidden && now - lastFrame >= 50) {
        lastFrame = now;
        const elapsed = (now - startedAt) / 1000;
        displayedGraphData.nodes.forEach((node) => {
          const cluster = node.__memoryCluster;
          if (!cluster) return;
          const angle = elapsed * renderSettings.memoryClusterRotationSpeed
            * cluster.speed * cluster.direction;
          const cos = Math.cos(angle);
          const sin = Math.sin(angle);
          setNodePosition(node, {
            x: cluster.center.x + cluster.offset.x * cos - cluster.offset.z * sin,
            y: cluster.center.y + cluster.offset.y,
            z: cluster.center.z + cluster.offset.x * sin + cluster.offset.z * cos,
          });
        });
        fgRef.current?.refresh?.();
      }
      frameId = window.requestAnimationFrame(animateClusters);
    };
    frameId = window.requestAnimationFrame(animateClusters);
    return () => window.cancelAnimationFrame(frameId);
  }, [displayedGraphData.nodes, graphDomain, memoryClustered, memoryExpanded,
    renderSettings.memoryClusterRotationSpeed, renderSettings.memoryClusterShowLinks]);

  // ===== 悬停放大（直接操作 3D 对象，避免重建全部节点导致卡顿）=====
  const prevHoverRef = useRef(null);
  useEffect(() => {
    const prev = prevHoverRef.current;
    if (prev && prev.__threeObj) prev.__threeObj.scale.set(1, 1, 1);
    if (hoveredNode && hoveredNode.__threeObj) {
      hoveredNode.__threeObj.scale.set(1.12, 1.12, 1.12);
    }
    prevHoverRef.current = hoveredNode;
  }, [hoveredNode]);

  const isNodeHighlighted = (node) => {
    if (!selectedNode) return false;
    if (node.id === selectedNode.id) return false;
    return connectedIds.has(node.id);
  };

  const getNodeOpacity = (node) => {
    if (!selectedNode) return 1;
    if (node.id === selectedNode.id) return 1;
    return connectedIds.has(node.id) ? 1 : 0.25;
  };

  const getMemoryClientColor = (node) => {
    if (!memoryExpanded) {
      if (node.original_node_type !== 'conversation_turn') return renderSettings.memorySecondaryColor;
      const client = String(node.payload?.origin_client || node.payload?.client || 'personal_agent').toLowerCase();
      if (client === 'personal_agent' || (node.payload?.origin_type || 'internal') === 'internal') return renderSettings.memoryInternalColor;
      if (client.includes('codex')) return renderSettings.memoryAgent1Color;
      if (client.includes('workbuddy')) return renderSettings.memoryAgent2Color;
      return renderSettings.memoryAgent3Color;
    }
    if (node.original_node_type === 'memory_entity') return '#c9adff';
    if (node.original_node_type === 'memory_point') return '#ffd17c';
    return '#a9d8ff';
  };

  const getPriorityOpacity = (node) => {
    if (selectedNode?.id === node.id) return 1;
    if (node.priority === 'context') return 0.38;
    if (node.priority === 'structure') return 0.68;
    return 1;
  };

  const getNodeRenderProfile = (node) => {
    if (graphDomain === 'memory') {
      const originalType = node.original_node_type;
      const primary = originalType === 'conversation_turn';
      if (!memoryExpanded) {
        const originalProfile = primary
          ? { size: renderSettings.memoryPrimarySize, brightness: renderSettings.memoryPrimaryBrightness, shape: renderSettings.memoryPrimaryShape, color: renderSettings.memoryPrimaryColor, glow: renderSettings.memoryPrimaryGlow }
          : { size: renderSettings.memorySecondarySize, brightness: renderSettings.memorySecondaryBrightness, shape: renderSettings.memorySecondaryShape, color: renderSettings.memorySecondaryColor, glow: renderSettings.memorySecondaryGlow };
        return { ...originalProfile, color: getMemoryClientColor(node) };
      }
      const settingsPrefix = memoryClustered ? 'memoryCluster' : 'memory';
      const expandedProfile = originalType === 'memory_entity'
        ? { size: renderSettings[`${settingsPrefix}EntitySize`], brightness: renderSettings[`${settingsPrefix}EntityBrightness`], shape: renderSettings[`${settingsPrefix}EntityShape`] }
        : (originalType === 'memory_point'
          ? { size: renderSettings[`${settingsPrefix}FactSize`], brightness: renderSettings[`${settingsPrefix}FactBrightness`], shape: renderSettings[`${settingsPrefix}FactShape`] }
          : { size: renderSettings[`${settingsPrefix}OriginalSize`], brightness: renderSettings[`${settingsPrefix}OriginalBrightness`], shape: renderSettings[`${settingsPrefix}OriginalShape`] });
      const typeGlow = 'soft';
      const profile = primary
        ? { ...expandedProfile, color: renderSettings.memoryPrimaryColor, glow: typeGlow }
        : { ...expandedProfile, color: renderSettings.memorySecondaryColor, glow: typeGlow };
      return { ...profile, color: getMemoryClientColor(node) };
    }
    if (graphDomain === 'note') {
      const originalType = node.original_node_type;
      if (NOTE_TOPIC_TYPES.has(originalType)) {
        return { size: renderSettings.noteTopicSize, brightness: renderSettings.noteTopicBrightness, shape: renderSettings.noteTopicShape, color: renderSettings.noteTopicColor, glow: renderSettings.noteTopicGlow };
      }
      if (NOTE_CONCEPT_TYPES.has(originalType)) {
        return { size: renderSettings.noteConceptSize, brightness: renderSettings.noteConceptBrightness, shape: renderSettings.noteConceptShape, color: renderSettings.noteConceptColor, glow: renderSettings.noteConceptGlow };
      }
      return { size: renderSettings.noteDocumentSize, brightness: renderSettings.noteDocumentBrightness, shape: renderSettings.noteDocumentShape, color: renderSettings.noteDocumentColor, glow: renderSettings.noteDocumentGlow };
    }
    if (graphDomain === 'project') {
      const codeBlock = ['function', 'method', 'block'].includes(node.original_node_type);
      return codeBlock
        ? { size: renderSettings.projectBlockSize, brightness: renderSettings.projectBlockBrightness, shape: renderSettings.projectBlockShape, color: renderSettings.projectBlockColor, glow: renderSettings.projectBlockGlow }
        : { size: renderSettings.projectOtherSize, brightness: renderSettings.projectOtherBrightness, shape: renderSettings.projectOtherShape, color: renderSettings.projectOtherColor, glow: renderSettings.projectOtherGlow };
    }
    return { size: renderSettings.generalSize, brightness: renderSettings.generalBrightness, shape: renderSettings.generalShape, color: renderSettings.generalColor, glow: renderSettings.generalGlow };
  };

  // ===== 节点大小（3D 用半径）—— 主节点放大一倍，形成星系层级 =====
  const getNodeRadius = (node) => {
    const profile = getNodeRenderProfile(node);
    if (graphDomain === 'memory') {
      if (!memoryExpanded) {
        // 个性化仍以 100% 为默认值；实际基础半径与整个可调区间统一缩小 50%。
        return 5.5 * renderSettings.memoryPrimarySize * (.78 + stableUnit(node.id, 211) * .62);
      }
      return 17 * profile.size;
    }
    if (graphDomain === 'note') {
      if (NOTE_TOPIC_TYPES.has(node.original_node_type)) return 30 * profile.size;
      return 17 * profile.size;
    }
    if (graphDomain === 'project' && node.original_node_type === 'module') return 88 * profile.size;
    if (node.node_type === 'domain') return 96 * profile.size;
    if (node.node_type === 'chapter') return 30 * profile.size;
    if (node.node_type === 'theory') return 16 * profile.size;
    return 12 * profile.size;
  };

  // ===== 亮度层级（主节点最亮，向叶子依次减弱，营造星系感）=====
  const getBrightnessTier = (node) => {
    const brightness = getNodeRenderProfile(node).brightness;
    if (graphDomain === 'memory' || graphDomain === 'note') return brightness;
    switch (node.node_type) {
      case 'domain':  return 1.0 * brightness;
      case 'chapter': return 0.62 * brightness;
      case 'theory':  return 0.4 * brightness;
      default:        return 0.28 * brightness;
    }
  };

  const getNodeShape = (node) => {
    return getNodeRenderProfile(node).shape;
  };

  // 领域 → 颜色映射（按领域在节点数组中的出现顺序，与 applyLayout 的 DOMAIN_INDEX 对齐）
  const domainColorById = useMemo(() => {
    const map = {};
    const doms = graphData.nodes.filter((n) => n.node_type === 'domain');
    doms.forEach((d, i) => { map[d.id] = DOMAIN_PALETTE[i % DOMAIN_PALETTE.length]; });
    return map;
  }, [graphData.nodes]);

  // ===== 创建节点（柔和模糊光点 + 亮核，营造星系光斑）=====
  const makeNodeObject = useCallback((node) => {
    const profile = getNodeRenderProfile(node);
    const configuredColor = profile.color;
    const isSelected = selectedNode?.id === node.id;
    const baseColorHex = isSelected ? '#ffffff' : (isNodeHighlighted(node) ? '#aa82ff' : configuredColor);

    let finalColor = baseColorHex;
    if (graphDomain !== 'memory' && node.is_learned && !isNodeHighlighted(node) && selectedNode?.id !== node.id) {
      finalColor = '#64e695';
    }

    const radius = getNodeRadius(node);
    const isDomain = graphDomain !== 'memory' && node.node_type === 'domain';
    const tier = getBrightnessTier(node);              // 主→叶 亮度依次减弱
    const shape = getNodeShape(node);
    const glowStyle = profile.glow;
    const glowMultiplier = glowStyle === 'none' ? 0 : 1;
    const opacityScale = getNodeOpacity(node) * getPriorityOpacity(node);
    const visualBrightness = graphDomain === 'memory' ? tier : Math.max(0.45, tier);
    const colorObj = new THREE.Color(finalColor);

    const group = new THREE.Group();

    // 三种记忆视图都使用一个 GPU 点云批量画星点。ForceGraph 中每个节点只保留
    // 不可见命中体和少量关系标签，避免每颗星拆成光晕、亮核等多次 draw call。
    if (graphDomain === 'memory') {
      const isRelated = selectedNode && (node.id === selectedNode.id || connectedIds.has(node.id));
      const hitR = isRelated ? Math.max(radius * 2.8, 22) : Math.max(radius * 2.2, 16);
      const hitMesh = new THREE.Mesh(
        MEMORY_HIT_GEOMETRY,
        new THREE.MeshBasicMaterial({ visible: false }),
      );
      hitMesh.scale.setScalar(hitR);
      if (selectedNode && !isRelated) hitMesh.raycast = () => {};
      group.add(hitMesh);
      if (isRelated) {
        const lineOccluder = new THREE.Mesh(
          new THREE.SphereGeometry(radius * .82, 8, 8),
          new THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: true, depthTest: true }),
        );
        lineOccluder.raycast = () => {};
        group.add(lineOccluder);
        if (persistentLabelIds.has(node.id)) group.add(makeTextSprite(node.label || node.id,
          isNodeHighlighted(node) ? '#c5a7ff' : '#ffffff', radius));
      }
      return group;
    }

    // 关系线在几何上连接节点中心；不透明暗核先写入深度，遮住星体内部的线段。
    const noteTopic = graphDomain === 'note' && NOTE_TOPIC_TYPES.has(node.original_node_type);
    // 遮挡球略小于笔记可见核心，避免两个深度面重合产生条纹。
    const lineOccluderScale = graphDomain === 'note' ? .30 : (noteTopic ? .96 : .91);
    const lineOccluder = new THREE.Mesh(
      new THREE.SphereGeometry(radius * lineOccluderScale, 20, 16),
      new THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: true, depthTest: true }),
    );
    lineOccluder.raycast = () => {};
    lineOccluder.renderOrder = 1;
    group.add(lineOccluder);

    // 笔记节点使用小实体核 + 原节点尺寸的柔光层；关系线穿过光层并止于实体核。
    if (graphDomain === 'note') {
      const isRelated = selectedNode && (node.id === selectedNode.id || connectedIds.has(node.id));
      if (shape === 'diamond') {
        const diamond = new THREE.Sprite(new THREE.SpriteMaterial({
          map: makeStarFlareTexture(finalColor), color: colorObj, transparent: true,
          opacity: opacityScale * visualBrightness, depthWrite: false, blending: THREE.AdditiveBlending,
        }));
        diamond.scale.set(radius * .667, radius * .667, 1);
        diamond.raycast = () => {};
        diamond.renderOrder = 3;
        group.add(diamond);
      } else {
        const sphere = new THREE.Mesh(
          new THREE.SphereGeometry(radius / 3, 22, 16),
          new THREE.MeshBasicMaterial({ color: colorObj, depthWrite: true, depthTest: true }),
        );
        sphere.raycast = () => {};
        sphere.renderOrder = 3;
        group.add(sphere);
      }
      const halo = new THREE.Sprite(new THREE.SpriteMaterial({
        map: makeHaloTexture(finalColor, 'note-dense'), color: colorObj, transparent: true,
        opacity: .68 * opacityScale * visualBrightness, depthWrite: false, depthTest: false,
        blending: THREE.AdditiveBlending,
      }));
      halo.scale.set(radius * 4, radius * 4, 1);
      halo.raycast = () => {};
      halo.renderOrder = 2;
      group.add(halo);
      const hitMesh = new THREE.Mesh(
        new THREE.SphereGeometry(Math.max(radius * (isRelated ? 1.45 : 1.05), 18), 7, 7),
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }),
      );
      if (selectedNode && !isRelated) hitMesh.raycast = () => {};
      group.add(hitMesh);
      if (isRelated && persistentLabelIds.has(node.id)) group.add(makeTextSprite(node.label || node.id, '#ffffff', radius));
      return group;
    }

    // ---- 主光晕：大而柔的模糊光点（核心视觉，替代原硬球体）----
    const glowSize = isSelected ? radius * 4.2 : radius * (3.2 + tier * 1.8);
    const glowMat = new THREE.SpriteMaterial({
      map: makeHaloTexture(finalColor, glowStyle),
      color: colorObj,
      transparent: true,
      opacity: glowMultiplier * opacityScale * visualBrightness * (isSelected ? 1 : (0.68 + tier * 0.42)),
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });
    const glow = new THREE.Sprite(glowMat);
    glow.renderOrder = 2;
    glow.scale.set(glowSize, glowSize, 1);
    glow.raycast = () => {};   // 只渲染，不参与点击命中（命中区由透明命中球精确控制）
    group.add(glow);

    // ---- 亮核：中心更亮的软核，给模糊光点一个锚定的"点" ----
    const coreSize = radius * (1.12 + tier * 0.5);
    const coreMat = new THREE.SpriteMaterial({
      map: makeCoreTexture(finalColor),
      transparent: true,
      opacity: opacityScale * visualBrightness * (0.8 + tier * 0.2),
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });
    const core = new THREE.Sprite(coreMat);
    core.renderOrder = 3;
    core.scale.set(coreSize, coreSize, 1);
    core.raycast = () => {};   // 只渲染，不参与点击命中
    group.add(core);

    if (graphDomain === 'memory' && memoryExpanded && shape === 'diamond') {
      const flare = new THREE.Sprite(new THREE.SpriteMaterial({
        map: makeStarFlareTexture(finalColor),
        transparent: true,
        opacity: opacityScale * Math.min(1, .76 + visualBrightness * .24),
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
      }));
      const flareSize = radius * 7.2;
      flare.renderOrder = 4;
      flare.scale.set(flareSize, flareSize, 1);
      flare.material.rotation = stableUnit(node.id, 751) * Math.PI;
      flare.raycast = () => {};
      group.add(flare);
    }

    if (isNodeHighlighted(node)) {
      const solidCore = new THREE.Mesh(
        new THREE.SphereGeometry(Math.max(1.25, radius * 0.16), 10, 10),
        new THREE.MeshBasicMaterial({ color: '#aa82ff', transparent: true, opacity: 0.96 * opacityScale, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending }),
      );
      solidCore.raycast = () => {};
      group.add(solidCore);
    }

    // ---- 主星额外超大日冕（超大淡光晕）----
    if (isDomain) {
      const corona = new THREE.Sprite(new THREE.SpriteMaterial({
        map: makeHaloTexture(finalColor, glowStyle),
        color: colorObj,
        transparent: true,
        opacity: glowMultiplier * opacityScale * visualBrightness * 0.4,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }));
      corona.scale.set(glowSize * 2.2, glowSize * 2.2, 1);
      corona.raycast = () => {};   // 只渲染，不参与点击命中
      group.add(corona);
    }

    // 是否为「相关节点」（选中节点本身或其直接关联节点）
    const isRelated = selectedNode && (node.id === selectedNode.id || connectedIds.has(node.id));

    // ---- 透明命中球：点击命中的唯一来源，半径收紧到「光点大小」----
    // 完全透明（opacity:0 但 visible:true），仅参与射线检测，不影响视觉。
    // 相关节点适度放大便于点击；关系模式下的无关节点完全关闭射线（不遮挡相关节点）。
    const hitR = isRelated
      ? Math.max(glowSize * 0.55, 22)      // 相关节点：稍大，易点
      : Math.max(glowSize * 0.45, 16);     // 普通节点：贴合可见光点
    const hitMesh = new THREE.Mesh(
      new THREE.SphereGeometry(hitR, 6, 6),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })
    );
    if (selectedNode && !isRelated) {
      hitMesh.raycast = () => {};   // 关系模式下无关节点：不参与射线，彻底不干扰
    }
    group.add(hitMesh);

    // 选中/关联节点：常驻名称标签（无需悬停即可看到），无关节点在关系模式下不显示
    if (isRelated && persistentLabelIds.has(node.id)) {
      const labelColor = isNodeHighlighted(node)
        ? '#c5a7ff'
        : (node.id === selectedNode?.id
            ? '#ffffff'
            : (node.node_type === 'domain'
                ? (['note', 'project'].includes(graphDomain) ? configuredColor : (domainColorById[node.id] || configuredColor))
                : configuredColor));
      const lbl = makeTextSprite(node.label || node.id, labelColor, radius);
      group.add(lbl);
    }

    return group;
  }, [selectedNode, connectedIds, persistentLabelIds, domainColorById, graphDomain, memoryExpanded, memoryClustered,
    renderSettings]);

  // ===== 自定义节点 =====
  const nodeThreeObject = useCallback((node) => {
    const object = makeNodeObject(node);
    node.__threeObj = object;
    return object;
  }, [makeNodeObject]);

  // Memory visual layer: one shader draw call for every visible star in the active memory view.
  useEffect(() => {
    const scene = fgRef.current?.scene?.();
    const previous = memoryPointCloudRef.current;
    if (previous && scene) scene.remove(previous);
    previous?.geometry?.dispose?.();
    previous?.material?.dispose?.();
    memoryPointCloudRef.current = null;
    if (!scene || graphDomain !== 'memory' || !displayedGraphData.nodes.length) return undefined;

    const nodes = displayedGraphData.nodes;
    const positions = new Float32Array(nodes.length * 3);
    const colors = new Float32Array(nodes.length * 3);
    const sizes = new Float32Array(nodes.length);
    const shapes = new Float32Array(nodes.length);
    nodes.forEach((node, index) => {
      positions[index * 3] = node.x || 0;
      positions[index * 3 + 1] = node.y || 0;
      positions[index * 3 + 2] = node.z || 0;
      const profile = getNodeRenderProfile(node);
      const isSelectedPoint = selectedNode?.id === node.id;
      const isConnectedPoint = connectedIds.has(node.id) && !isSelectedPoint;
      const color = new THREE.Color(isSelectedPoint
        ? '#ffffff' : (isConnectedPoint ? '#aa82ff' : profile.color));
      if (isConnectedPoint) color.multiplyScalar(1.42);
      else if (graphDomain === 'memory' && memoryExpanded && selectedNode && !isSelectedPoint) color.multiplyScalar(.60);
      else if (memoryClustered && !isSelectedPoint) color.multiplyScalar(.82 * profile.brightness);
      else if (!memoryExpanded && !isSelectedPoint) color.multiplyScalar(profile.brightness);
      color.toArray(colors, index * 3);
      const selectedScale = isSelectedPoint ? 1.5 : (isConnectedPoint ? 1.72 : 1);
      // 集群复用记忆信息的形状与材质，只缩小常态星点，让球形约束内留出呼吸空间。
      const clusterScale = memoryClustered ? 3.2 : 1;
      sizes[index] = getNodeRadius(node) * 9 * selectedScale * clusterScale;
      shapes[index] = getNodeShape(node) === 'diamond' ? 1 : 0;
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
    geometry.setAttribute('aShape', new THREE.BufferAttribute(shapes, 1));
    const material = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
      vertexColors: true,
      vertexShader: `attribute float aSize; attribute float aShape; varying vec3 vColor; varying float vShape;
        void main(){ vColor=color; vShape=aShape; vec4 mv=modelViewMatrix*vec4(position,1.0);
        gl_PointSize=clamp(aSize*(360.0/max(120.0,-mv.z)),2.0,150.0); gl_Position=projectionMatrix*mv; }`,
      fragmentShader: `varying vec3 vColor; varying float vShape;
        void main(){ vec2 p=gl_PointCoord*2.0-1.0; float r=length(p); float alpha;
        if(vShape>.5){ vec2 q=abs(p); float inner=.32; float edge=q.x>=q.y ? q.y-inner*(.875-q.x)/(.875-inner) : q.x-inner*(.875-q.y)/(.875-inner);
          float body=1.0-smoothstep(-.055,.055,edge); float glow=(1.0-smoothstep(.08,1.0,r))*.58; alpha=max(body,glow);
        } else { alpha=(1.0-smoothstep(.05,1.0,r))*(.55+.45*(1.0-smoothstep(0.0,.28,r))); }
        if(alpha<.015) discard; gl_FragColor=vec4(vColor,alpha); }`,
    });
    const cloud = new THREE.Points(geometry, material);
    cloud.frustumCulled = false;
    cloud.renderOrder = 3;
    cloud.raycast = () => {};
    cloud.userData.nodes = nodes;
    scene.add(cloud);
    memoryPointCloudRef.current = cloud;
    let frame = 0;
    let lastSync = 0;
    const sync = (now) => {
      if (now - lastSync >= 50) {
        lastSync = now;
        const attribute = geometry.getAttribute('position');
        nodes.forEach((node, index) => {
          attribute.setXYZ(index, node.x || 0, node.y || 0, node.z || 0);
        });
        attribute.needsUpdate = true;
      }
      frame = window.requestAnimationFrame(sync);
    };
    frame = window.requestAnimationFrame(sync);
    return () => {
      window.cancelAnimationFrame(frame);
      scene.remove(cloud);
      geometry.dispose();
      material.dispose();
      if (memoryPointCloudRef.current === cloud) memoryPointCloudRef.current = null;
    };
  }, [connectedIds, displayedGraphData.nodes, graphDomain, graphSize.height, graphSize.width,
    memoryExpanded, memoryClustered, renderSettings, selectedNode]);

  // ===== 连线颜色 =====
  const linkColor = useCallback((link) => {
    const sId = typeof link.source === 'object' ? link.source.id : link.source;
    const tId = typeof link.target === 'object' ? link.target.id : link.target;
    const isHighlighted = selectedNode && (sId === selectedNode.id || tId === selectedNode.id);
    const configuredLineColor = memoryClustered
      ? renderSettings.memoryClusterLineColor
      : renderSettings.lineColor;
    const base = isHighlighted ? '#a98bff' : configuredLineColor;
    if (!['memory', 'note'].includes(graphDomain)) return base;
    const rgb = hexToRgb(base);
    const defaultAlpha = graphDomain === 'note' ? .52 : (memoryClustered ? .42 : .52);
    const alpha = Math.max(0, Math.min(1, relationRevealRef.current)) * (isHighlighted ? .92 : defaultAlpha);
    return `rgba(${rgb.r},${rgb.g},${rgb.b},${alpha})`;
  }, [selectedNode, renderSettings.lineColor, renderSettings.memoryClusterLineColor,
    graphDomain, memoryClustered]);

  const linkVisibility = useCallback((link) => {
    const source = typeof link.source === 'object' ? link.source.id : link.source;
    const target = typeof link.target === 'object' ? link.target.id : link.target;
    if (graphDomain === 'note') {
      const sourceNode = nodeMapRef.current?.get(source);
      const targetNode = nodeMapRef.current?.get(target);
      const types = new Set([sourceNode?.original_node_type, targetNode?.original_node_type]);
      const isTopicConcept = types.has('wiki_topic')
        && (types.has('wiki_concept') || types.has('knowledge_point') || types.has('wiki_synthesis'));
      return isTopicConcept || Boolean(selectedNode && (source === selectedNode.id || target === selectedNode.id));
    }
    if (graphDomain !== 'memory') return true;
    if (memoryClustered) {
      return renderSettings.memoryClusterShowLinks
        || Boolean(selectedNode && (source === selectedNode.id || target === selectedNode.id));
    }
    if (!selectedNode) return false;
    return source === selectedNode.id || target === selectedNode.id;
  }, [graphDomain, memoryClustered, selectedNode, renderSettings.memoryClusterShowLinks]);

  const relationParticleSpeed = useCallback((link) => {
    if (!selectedNode) return 0;
    const source = typeof link.source === 'object' ? link.source.id : link.source;
    return source === selectedNode.id ? .016 : -.016;
  }, [selectedNode]);

  const linkWidth = useCallback((link) => {
    const sId = typeof link.source === 'object' ? link.source.id : link.source;
    const tId = typeof link.target === 'object' ? link.target.id : link.target;
    const base = selectedNode && (sId === selectedNode.id || tId === selectedNode.id)
      ? 0.85
      : (link.edge_type === 'contains' ? 0.7 : (link.edge_type === 'imports' ? 0.65 : 0.4));
    const thickness = memoryClustered
      ? renderSettings.memoryClusterLineThickness
      : renderSettings.lineThickness;
    const memoryMultiplier = graphDomain === 'note'
      ? 2
      : graphDomain === 'memory' && memoryExpanded
      ? (memoryClustered ? 1.35 : 2)
      : 1;
    return base * thickness * memoryMultiplier;
  }, [graphDomain, memoryExpanded, memoryClustered, selectedNode, renderSettings.lineThickness,
    renderSettings.memoryClusterLineThickness]);

  const fetchArticle = useCallback(async (node) => {
    const isWikiPage = graphDomain === 'note' && node?.payload?.page_id;
    if (!node || (!node.article_path && !isWikiPage)) return;
    setArticleLoading(true);
    try {
      let endpoint = `${apiBase}/api/graph/article?path=${encodeURIComponent(node.article_path)}`;
      if (graphDomain === 'memory') {
        endpoint = node.payload.turn_id
          ? `${apiBase}/api/graphs/memory/turns/${encodeURIComponent(node.payload.turn_id)}`
          : `${apiBase}/api/graphs/memory/${encodeURIComponent(node.payload.memory_id)}/trace`;
      } else if (graphDomain === 'note') {
        const isSourcePage = node.original_node_type === 'wiki_source' && node.payload?.source_ref;
        endpoint = isSourcePage
          ? (node.payload.source_kind === 'generated_note'
              ? `${apiBase}/api/library/notes/${encodeURIComponent(node.payload.source_ref)}`
              : `${apiBase}/api/library/notes/documents/${encodeURIComponent(node.payload.source_ref)}/content`)
          : (isWikiPage
              ? `${apiBase}/api/library/wiki/pages/${encodeURIComponent(node.payload.page_id)}`
              : `${apiBase}/api/library/notes/${encodeURIComponent(node.payload.filename)}`);
      } else if (graphDomain === 'project') {
        endpoint = `${apiBase}/api/library/code-projects/${node.payload.project_id}/file?file_path=${encodeURIComponent(node.payload.file_path)}`;
      }
      const res = await fetch(endpoint);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || data.detail || `文章请求失败（${res.status}）`);
      if (graphDomain === 'project') {
        const source = (data.source_lines || [])
          .map((line, index) => `${String(index + 1).padStart(4, ' ')}  ${line}`)
          .join('\n');
        setArticleContent({
          content: `## ${data.file_name || node.label}\n\n${data.file_role || ''}\n\n\`\`\`python\n${source}\n\`\`\``,
        });
      } else if (graphDomain === 'memory') {
        if (node.payload.turn_id) {
          const source = data.origin_type === 'external'
            ? `外部 · ${data.origin_client || 'unknown'}`
            : '内部 · personal_agent';
          setArticleContent({
            content: `## ${data.conversation_title || node.label}\n\n> ${source} · ${data.created_at || ''}\n\n### 对话概括\n\n${data.display_summary || node.description || ''}\n\n---\n\n### 提问原文\n\n${data.user_message || ''}\n\n### 回答原文\n\n${data.assistant_message || ''}`,
            view: 'conversation',
            title: data.conversation_title || node.label,
            source,
            createdAt: data.created_at || '',
            summary: data.display_summary || node.description || '',
            userMessage: data.user_message || '',
            assistantMessage: data.assistant_message || '',
          });
        } else {
          const memory = data.memory || {};
          const source = memory.origin_type === 'external'
            ? `外部 · ${memory.origin_client || 'unknown'}`
            : '内部 · personal_agent';
          setArticleContent({
            content: `## ${memory.summary || '长期记忆'}\n\n> ${source} · ${memory.created_at || ''}\n\n${memory.content || ''}`,
          });
        }
      } else {
        if (graphDomain === 'note' && node.original_node_type === 'wiki_source') {
          setArticleContent({
            ...data,
            content: data.content || '',
            sourceDocumentId: node.payload.source_kind === 'generated_note' ? '' : node.payload.source_ref,
          });
          return;
        }
        const focusIndex = node.__focusSegment;
        if (graphDomain === 'note' && Number.isInteger(focusIndex) && data.segments?.[focusIndex]) {
          const segment = data.segments[focusIndex];
          setArticleContent({
            ...data,
            content: `> 已定位知识点关联段落：${segment.title || `第 ${focusIndex + 1} 段`}\n\n${data.content || ''}`,
          });
        } else {
          setArticleContent({
            ...data,
            content: data.content || data.body_markdown || '',
            wikiPageId: graphDomain === 'note' ? node.payload?.page_id : '',
          });
        }
      }
    } catch (err) {
      console.error('加载文章失败:', err);
    } finally {
      setArticleLoading(false);
    }
  }, [apiBase, graphDomain]);

  const loadProjectChildren = useCallback(async (node) => {
    if (
      graphDomain !== 'project'
      || node.original_node_type !== 'file'
      || !node.payload?.project_id
      || loadedProjectNodesRef.current.has(node.id)
    ) return;
    loadedProjectNodesRef.current.add(node.id);
    try {
      const endpoint = `${apiBase}/api/graphs/projects/${node.payload.project_id}/children?node_id=${encodeURIComponent(node.id)}`;
      const response = await fetch(endpoint);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.message || data.detail || '项目子图加载失败');
      const childNodes = (data.nodes || []).map((raw) => ({
        ...raw,
        payload: raw.payload || {},
        original_node_type: raw.node_type || 'block',
        node_type: ['function', 'method', 'block'].includes(raw.node_type)
          ? 'tech'
          : raw.node_type === 'class' ? 'chapter' : 'theory',
        description: raw.description || raw.summary || '',
        parent: node.id,
        article_path: raw.payload?.file_path ? `domain://project/${raw.id}` : raw.article_path,
        __rawLinks: [node.id],
      }));
      const childLinks = (data.edges || data.links || []).map((raw) => ({
        source: raw.source,
        target: raw.target,
        edge_type: raw.edge_type || raw.label || 'contains',
        label: raw.label,
        payload: raw.payload || {},
      }));
      setGraphData((previous) => {
        const knownNodeIds = new Set(previous.nodes.map((item) => item.id));
        const knownLinks = new Set(previous.links.map((item) => {
          const source = typeof item.source === 'object' ? item.source.id : item.source;
          const target = typeof item.target === 'object' ? item.target.id : item.target;
          return `${source}->${target}`;
        }));
        const nextNodes = [
          ...previous.nodes,
          ...childNodes.filter((item) => !knownNodeIds.has(item.id)),
        ];
        const nextLinks = [
          ...previous.links,
          ...childLinks.filter((item) => !knownLinks.has(`${item.source}->${item.target}`)),
        ];
        const nodeMap = new Map(nextNodes.map((item) => [item.id, item]));
        childLinks.forEach((link) => {
          if (nodeMap.has(link.source)) nodeMap.get(link.source).__rawLinks.push(link.target);
          if (nodeMap.has(link.target)) nodeMap.get(link.target).__rawLinks.push(link.source);
        });
        applyProjectTreeLayout(nextNodes, nodeMap);
        nodeMapRef.current = nodeMap;
        graphDataRef.current = { nodes: nextNodes, links: nextLinks };
        setFileTree(buildFileTree(nextNodes));
        return { nodes: nextNodes, links: nextLinks };
      });
    } catch (error) {
      loadedProjectNodesRef.current.delete(node.id);
      setGraphError(error.message || '项目子图加载失败');
    }
  }, [apiBase, graphDomain]);

  const getNodeCardPosition = useCallback((node) => {
    if (!node || !fgRef.current) return null;
    const point = fgRef.current.graph2ScreenCoords(node.x || 0, node.y || 0, node.z || 0);
    const panelWidth = 320;
    const panelHeight = 440;
    const visualClearance = graphDomain === 'note'
      ? Math.min(190, Math.max(44, getNodeRadius(node) * 1.65))
      : 20;
    const x = point.x + visualClearance + panelWidth <= graphSize.width
      ? point.x + visualClearance
      : point.x - panelWidth - visualClearance;
    return {
      x: Math.max(12, Math.min(graphSize.width - panelWidth - 12, x)),
      y: Math.max(72, Math.min(graphSize.height - panelHeight - 12, point.y - 44)),
    };
  }, [graphDomain, graphSize.width, graphSize.height, renderSettings]);

  // ===== 节点点击 =====
  // 行为：
  //  - 单击节点：高亮（变亮）+ 底部立即弹出详情面板（含节点信息、阅读文章按钮）
  //  - 视图不变，不做相机移动
  //  - 去选（恢复默认旋转）由空白处点击负责
  const handleNodeClick = useCallback((node) => {
    // 关系模式下，仅允许点击相关节点（选中节点或其关联节点），无关节点忽略
    if (selectedNode && !(node.id === selectedNode.id || connectedIds.has(node.id))) {
      return;
    }
    if (selectedNode?.id === node.id) {
      // 同一节点重复点击：保持选中状态，不做额外操作
      setSelectionCardVisible(true);
      setPinnedCardPosition(getNodeCardPosition(node));
      return;
    }
    // 单击即选中 + 立即预加载文章（若有 article_path）
    const relatedEdge = selectedNode?.original_node_type === 'knowledge_point'
      ? filteredData.links.find((link) => {
          const source = typeof link.source === 'object' ? link.source.id : link.source;
          const target = typeof link.target === 'object' ? link.target.id : link.target;
          return source === selectedNode.id && target === node.id;
        })
      : null;
    const nextNode = relatedEdge
      ? { ...node, __focusSegment: relatedEdge.payload?.segment_index }
      : node;
    setPinnedCardPosition(getNodeCardPosition(node));
    setSelectionCardVisible(true);
    setSelectedNode(nextNode);
    loadProjectChildren(nextNode);
    if (nextNode.article_path) {
      fetchArticle(nextNode); // 异步加载，不阻塞 UI
    }
  }, [selectedNode, connectedIds, fetchArticle, filteredData.links, getNodeCardPosition, loadProjectChildren]);

  useEffect(() => {
    window.cancelAnimationFrame(relationRevealFrameRef.current);
    if (graphDomain !== 'memory' || !selectedNode) {
      relationRevealRef.current = 1;
      setRelationAnimationActive(false);
      fgRef.current?.refresh?.();
      return undefined;
    }
    relationRevealRef.current = 0;
    setRelationAnimationActive(true);
    const startedAt = performance.now();
    const animate = (now) => {
      const progress = Math.min(1, (now - startedAt) / 1000);
      relationRevealRef.current = 1 - Math.pow(1 - progress, 3);
      fgRef.current?.refresh?.();
      if (progress < 1) relationRevealFrameRef.current = window.requestAnimationFrame(animate);
      else setRelationAnimationActive(false);
    };
    relationRevealFrameRef.current = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(relationRevealFrameRef.current);
  }, [graphDomain, selectedNode]);

  const handleNodeHover = useCallback((node) => {
    // 关系展开后名称已经常驻；关闭悬停缩放，避免整个节点组（含名称）
    // 在 1× / 1.12× 之间反复切换造成文字视觉闪烁。
    if (selectedNode) {
      setHoveredNode(null);
      setHoverCardPosition(null);
      document.body.style.cursor = node && (node.id === selectedNode.id || connectedIds.has(node.id))
        ? 'pointer' : 'default';
      return;
    }
    // 关系模式下，无关节点完全不响应（不弹名称、不变光标、不变大）
    setHoveredNode(node);
    setHoverCardPosition(getNodeCardPosition(node));
    document.body.style.cursor = node ? 'pointer' : 'default';
  }, [selectedNode, connectedIds, getNodeCardPosition]);

  const handleBackgroundClick = useCallback(() => {
    setSelectedNode(null);
    setSelectionCardVisible(true);
    setPinnedCardPosition(null);
    setArticleContent(null);
    setShowArticle(false); // 关闭文章面板，旋转由 autoRotate 自动恢复
  }, []);

  // ===== 布局切换：0.6s easeOutCubic 位置过渡（tween）=====
  const transitionTo = (mode) => {
    const fg = fgRef.current;
    if (!fg) { applyLayout(graphData.nodes, mode, nodeMapRef.current); return; }
    if (isTransitioning.current) return;

    const nodes = graphData.nodes;
    // 1) 记录旧位置（applyLayout 会改写 n.x/y/z 为目标）
    const oldPos = new Map();
    nodes.forEach(n => oldPos.set(n.id, { x: n.x, y: n.y, z: n.z }));

    // 2) 用 applyLayout 算出目标坐标（写入 n.fx/fy/fz 与 n.x/y/z）
    applyLayout(nodes, mode, nodeMapRef.current);

    // 3) 记录目标并撤销钉死，以便手动插值（否则力导会把 x 拉回旧钉点）
    const targets = new Map();
    nodes.forEach(n => {
      targets.set(n.id, { x: n.fx, y: n.fy, z: n.fz });
      n.fx = undefined; n.fy = undefined; n.fz = undefined;
    });

    isTransitioning.current = true;
    const duration = 600;
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const e = 1 - Math.pow(1 - t, 3); // easeOutCubic
      nodes.forEach(n => {
        const tg = targets.get(n.id);
        const op = oldPos.get(n.id);
        n.x = op.x + (tg.x - op.x) * e;
        n.y = op.y + (tg.y - op.y) * e;
        n.z = op.z + (tg.z - op.z) * e;
      });
      if (fg) fg.refresh();
      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        // 钉回新位置并回正视角
        nodes.forEach(n => {
          const tg = targets.get(n.id);
          n.fx = tg.x; n.fy = tg.y; n.fz = tg.z;
          n.x = tg.x; n.y = tg.y; n.z = tg.z;
        });
        isTransitioning.current = false;
      }
    };
    requestAnimationFrame(step);
  };

  // 顶栏「总览 / 分域」按钮：切换布局模式（不保留选中）
  const handleToggleView = () => {
    const next = viewMode === 'clusters' ? 'galaxy' : 'clusters';
    setSelectedNode(null);
    setArticleContent(null);
    setShowArticle(false);
    setViewMode(next);
    transitionTo(next);
  };

  const handleToggleMemoryExpanded = (requestedState) => {
    const next = typeof requestedState === 'boolean' ? requestedState : !memoryExpanded;
    if (next === memoryExpanded) return;
    galaxyTransitionUntilRef.current = performance.now() + 780;
    if (!next && selectedNode?.original_node_type !== 'conversation_turn') {
      setSelectedNode(null);
      setArticleContent(null);
      setShowArticle(false);
    }
    if (renderSettings.memoryGalaxyEnabled) {
      const movingNodes = graphData.nodes.filter(
        (node) => node.original_node_type === 'conversation_turn',
      );
      const starts = movingNodes.map((node) => ({
        node, x: node.x || 0, y: node.y || 0, z: node.z || 0,
        target: next
          ? node.__relationPosition
          : (node.__galaxyPosition
            ? transformMemoryGalaxyPosition(node.__galaxyPosition, galaxyRotationRef.current)
            : null),
      })).filter((item) => item.target);
      const startedAt = performance.now();
      const animate = (now) => {
        const progress = Math.min(1, (now - startedAt) / 760);
        const eased = 1 - Math.pow(1 - progress, 3);
        starts.forEach(({ node, x, y, z, target }) => setNodePosition(node, {
          x: x + (target.x - x) * eased,
          y: y + (target.y - y) * eased,
          z: z + (target.z - z) * eased,
        }));
        fgRef.current?.refresh?.();
        if (progress < 1) requestAnimationFrame(animate);
      };
      requestAnimationFrame(animate);
    }
    setMemoryExpanded(next);
    window.setTimeout(() => {
      focusMemoryView(next, 700);
    }, 80);
  };

  const handleMemoryView = (mode) => {
    const wantsExpanded = mode !== 'galaxy';
    setSelectedNode(null);
    setPinnedCardPosition(null);
    setArticleContent(null);
    setShowArticle(false);
    setMemoryClustered(false);
    if (memoryExpanded !== wantsExpanded) handleToggleMemoryExpanded(wantsExpanded);
  };

  const handleSaveRenderSettings = () => {
    const next = { ...DEFAULT_RENDER_SETTINGS, ...renderSettingsDraft };
    const spatialLayoutChanged = next.memorySpatialLayout !== renderSettings.memorySpatialLayout
      || next.memorySpatialScale !== renderSettings.memorySpatialScale
      || next.memoryClusterSpatialScale !== renderSettings.memoryClusterSpatialScale;
    localStorage.setItem('agentforge.graphRenderSettings', JSON.stringify(next));
    setRenderSettings(next);
    setGraphData((current) => {
      // 空间尺寸改变时直接由重新载入逻辑生成新的球内随机坐标；不要先套用旧
      // __base 坐标，否则原文节点会短暂被缩放到中心并污染 relationPosition。
      if (graphDomain === 'memory' && memoryExpanded && spatialLayoutChanged) return current;
      applyPersonalizedLayout(current.nodes, next);
      if (graphDomain === 'note') applyNoteSemanticLayout(current.nodes, current.links);
      if (graphDomain === 'memory') {
        current.nodes.forEach((node, index) => {
          node.__relationPosition = { x: node.x || 0, y: node.y || 0, z: node.z || 0 };
          if (node.original_node_type === 'conversation_turn') {
            node.__galaxyPosition = galaxyPositionForStyle(
              node, index, next.memoryGalaxyStyle,
            );
            if (!memoryExpanded && next.memoryGalaxyEnabled) {
              setNodePosition(node, transformMemoryGalaxyPosition(
                node.__galaxyPosition, galaxyRotationRef.current,
              ));
            }
          }
        });
      }
      return { nodes: [...current.nodes], links: [...current.links] };
    });
    // 个性化设置只刷新材质与布局，不改变用户当前镜头距离。
    window.setTimeout(() => fgRef.current?.refresh?.(), 50);
    if (spatialLayoutChanged) setGraphRefreshKey((value) => value + 1);
  };

  const handleResetRenderSettings = () => {
    setRenderSettingsDraft({ ...DEFAULT_RENDER_SETTINGS });
  };

  const renderNodeStyleSection = (title, prefix) => {
    const key = (suffix) => `${prefix}${suffix}`;
    const updateValue = (suffix, value) => setRenderSettingsDraft((current) => ({
      ...current,
      [key(suffix)]: value,
    }));
    return <section key={prefix}>
      <h4>{title}</h4>
      <label>大小 <output>{renderSettingsDraft[key('Size')].toFixed(1)}×</output><input type="range" min="0.4" max="1.8" step="0.1" value={renderSettingsDraft[key('Size')]} onChange={(event) => updateValue('Size', Number(event.target.value))} /></label>
      <label>亮度 <output>{Math.round(renderSettingsDraft[key('Brightness')] * 100)}%</output><input type="range" min="0.1" max="1" step="0.05" value={renderSettingsDraft[key('Brightness')]} onChange={(event) => updateValue('Brightness', Number(event.target.value))} /></label>
      <label>颜色<input type="color" value={renderSettingsDraft[key('Color')]} onChange={(event) => updateValue('Color', event.target.value)} /></label>
      <label>星点形状<select value={renderSettingsDraft[key('Shape')]} onChange={(event) => updateValue('Shape', event.target.value)}><option value="circle">圆形</option><option value="diamond">菱形</option><option value="square">方形</option></select></label>
      <label>外层光<select value={renderSettingsDraft[key('Glow')]} onChange={(event) => updateValue('Glow', event.target.value)}><option value="soft">柔和扩散</option><option value="compact">紧凑光核</option><option value="halo">环形光晕</option><option value="none">关闭外层光</option></select></label>
    </section>;
  };

  const renderNoteStyleSection = (title, prefix) => {
    const sizeKey = `${prefix}Size`;
    const colorKey = `${prefix}Color`;
    const shapeKey = `${prefix}Shape`;
    return <section key={prefix}>
      <h4>{title}</h4>
      <label>大小 <output>{renderSettingsDraft[sizeKey].toFixed(1)}×</output><input type="range" min="0.4" max="2" step="0.05" value={renderSettingsDraft[sizeKey]} onChange={(event) => setRenderSettingsDraft((current) => ({ ...current, [sizeKey]: Number(event.target.value) }))} /></label>
      <label>颜色<input type="color" value={renderSettingsDraft[colorKey]} onChange={(event) => setRenderSettingsDraft((current) => ({ ...current, [colorKey]: event.target.value }))} /></label>
      <label>星点形状<select value={renderSettingsDraft[shapeKey]} onChange={(event) => setRenderSettingsDraft((current) => ({ ...current, [shapeKey]: event.target.value }))}><option value="circle">圆形</option><option value="diamond">内凹菱形</option></select></label>
    </section>;
  };

  const renderExpandedMemoryStyleCards = (clustered) => {
    const prefix = clustered ? 'memoryCluster' : 'memory';
    return [
      ['原文星点', `${prefix}OriginalSize`, `${prefix}OriginalBrightness`, `${prefix}OriginalShape`],
      ['事实星点', `${prefix}FactSize`, `${prefix}FactBrightness`, `${prefix}FactShape`],
      ['实体星点', `${prefix}EntitySize`, `${prefix}EntityBrightness`, `${prefix}EntityShape`],
    ].map(([label, sizeKey, brightnessKey, shapeKey]) => (
      <details className="sf-render-card" key={sizeKey}>
        <summary>{label} <span>›</span></summary>
        <div>
          <label>大小 <output>{Math.round(renderSettingsDraft[sizeKey] * 100)}%</output><input type="range" min="0.5" max="2" step="0.05" value={renderSettingsDraft[sizeKey]} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, [sizeKey]: Number(event.target.value) })} /></label>
          <label>亮度 <output>{Math.round(renderSettingsDraft[brightnessKey] * 100)}%</output><input type="range" min="0.5" max="2" step="0.05" value={renderSettingsDraft[brightnessKey]} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, [brightnessKey]: Number(event.target.value) })} /></label>
          <label>形状<select value={renderSettingsDraft[shapeKey]} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, [shapeKey]: event.target.value })}><option value="circle">圆形</option><option value="diamond">内凹四角星芒</option></select></label>
        </div>
      </details>
    ));
  };

  // 左侧目录点击节点 = 等同于直接单击节点（一步到位：选中+预加载+详情面板）
  const handleSidebarNodeClick = useCallback((treeNode) => {
    if (graphDomain === 'memory' && treeNode.isSourceFilter) {
      setMemoryClientFilter((current) => current === treeNode.client ? 'all' : treeNode.client);
      setSelectedNode(null);
      setHoveredNode(null);
      return;
    }
    const node = graphData.nodes.find(n => n.id === treeNode.id);
    if (node) {
      setPinnedCardPosition(getNodeCardPosition(node));
      setSelectedNode(node);
      loadProjectChildren(node);
      if (node.article_path) {
        fetchArticle(node);
      }
    }
  }, [graphData.nodes, graphDomain, fetchArticle, getNodeCardPosition, loadProjectChildren]);

  const toggleExpand = (id) => {
    setExpandedDomains(prev => ({ ...prev, [id]: !prev[id] }));
  };

  // 仅拉取文章数据写入 articleContent，不自动打开弹窗（预览/弹窗复用）


  // 打开“查看完整内容”弹窗
  const loadArticle = useCallback(async (node) => {
    await fetchArticle(node);
    setShowArticle(true);
  }, [fetchArticle]);

  const saveSessionName = async (item) => {
    if (renamingSessionId !== item.id) return;
    const title = sessionNameDraft.trim();
    setRenamingSessionId('');
    if (!title || title === item.label) return;
    if (sessionRenameInFlightRef.current === item.sessionId) return;
    sessionRenameInFlightRef.current = item.sessionId;
    try {
      const response = await fetch(`${apiBase}/api/graphs/memory/sessions/${encodeURIComponent(item.sessionId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || '重命名失败');
      const savedTitle = result.title || title;
      // 会话重命名只更新目录树；不重新装载 ForceGraph 数据，避免其清空自定义银河层。
      const renameTreeItem = (items) => items.map((treeItem) => {
        if (treeItem.id === item.id) {
          return { ...treeItem, label: savedTitle, title: savedTitle };
        }
        if (!treeItem.children?.length) return treeItem;
        return { ...treeItem, children: renameTreeItem(treeItem.children) };
      });
      setFileTree((current) => renameTreeItem(current));
    } catch (error) {
      setGraphError(error.message || '重命名失败');
    } finally {
      if (sessionRenameInFlightRef.current === item.sessionId) {
        sessionRenameInFlightRef.current = '';
      }
    }
  };

  const deleteMemorySession = async (item) => {
    try {
      const isTurn = item.original_node_type === 'conversation_turn';
      const endpoint = isTurn
        ? `${apiBase}/api/graphs/memory/turns/${encodeURIComponent(item.payload?.turn_id || String(item.id).replace(/^turn:/, ''))}`
        : `${apiBase}/api/graphs/memory/sessions/${encodeURIComponent(item.sessionId)}`;
      const response = await fetch(endpoint, { method: 'DELETE' });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || '删除失败');
      setDeleteSessionTarget(null);
      setSelectedNode(null);
      setGraphRefreshKey((value) => value + 1);
    } catch (error) {
      setDeleteSessionTarget(null);
      setGraphError(error.message || '删除失败');
    }
  };

  const requestDeleteSession = (item) => {
    if (localStorage.getItem('personal-agent:skip-memory-delete-confirm') === 'true') deleteMemorySession(item);
    else { setRememberDeleteChoice(false); setDeleteSessionTarget(item); }
  };

  const startSidebarResize = (event) => {
    event.preventDefault();
    const startX = event.clientX; const startWidth = sidebarWidth;
    const move = (moveEvent) => setSidebarWidth(Math.max(240, Math.min(560, startWidth + moveEvent.clientX - startX)));
    const finish = () => {
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', finish);
    };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', finish, { once: true });
  };

  const renderTree = (items, depth = 0) => {
    return items.map(item => {
      const hasChildren = item.children && item.children.length > 0;
      const isExpanded = expandedDomains[item.id];
      return (
        <div key={item.id} style={{ paddingLeft: depth * 18 }}>
          <div
            className={`sf-tree-node ${selectedNode?.id === item.id ? 'active' : ''} ${item.isSourceFilter && memoryClientFilter === item.client ? 'source-filter-active' : ''}`}
            onClick={() => handleSidebarNodeClick(item)}
          >
            <span
              className="sf-expand-toggle"
              onClick={(e) => {
                e.stopPropagation();
                if (hasChildren) toggleExpand(item.id);
              }}
            >
              {hasChildren ? (isExpanded ? '▾' : '▸') : item.node_type === 'domain' ? '▾' : ''}
            </span>
            <span className="sf-node-icon">{item.icon}</span>
            {renamingSessionId === item.id ? (
              <input
                className="sf-session-rename-input"
                value={sessionNameDraft}
                autoFocus
                maxLength={120}
                onClick={(event) => event.stopPropagation()}
                onChange={(event) => setSessionNameDraft(event.target.value)}
                onBlur={() => saveSessionName(item)}
                onKeyDown={(event) => {
                  event.stopPropagation();
                  if (event.key === 'Enter') saveSessionName(item);
                  if (event.key === 'Escape') setRenamingSessionId('');
                }}
              />
            ) : (
              <span
                className="sf-node-label"
                onDoubleClick={(event) => {
                  if (!item.sessionId) return;
                  event.stopPropagation();
                  setRenamingSessionId(item.id);
                  setSessionNameDraft(item.label);
                }}
              >{item.label}</span>
            )}
            {item.sessionId && item.distillationStatus !== 'distilled' && (
              <span className="sf-distilling-indicator" title={item.distillationStatus === 'processing' ? '正在蒸馏' : '等待蒸馏'} aria-label={item.distillationStatus === 'processing' ? '正在蒸馏' : '等待蒸馏'} />
            )}
            {item.sessionId && renamingSessionId !== item.id && (
              <button
                className="sf-session-rename-button"
                type="button"
                title="重命名会话"
                onClick={(event) => {
                  event.stopPropagation();
                  setRenamingSessionId(item.id);
                  setSessionNameDraft(item.label);
                }}
              >✎</button>
            )}
            {(item.sessionId || item.original_node_type === 'conversation_turn') && renamingSessionId !== item.id && <button className="sf-session-delete-button" type="button" title={item.original_node_type === 'conversation_turn' ? '删除这条对话及相关记忆' : '删除会话及相关记忆'} onClick={(event) => { event.stopPropagation(); requestDeleteSession(item); }}>×</button>}
            {item.priority === 'key' && <span className="sf-priority-badge key">重点</span>}
            {item.priority === 'context' && <span className="sf-priority-badge context">了解</span>}
            {item.is_learned && <span className="sf-learned-badge">✦</span>}
            {item.mastery_score > 0 && (
              <span className="sf-mastery-badge">{Math.round(item.mastery_score)}%</span>
            )}
          </div>
          {hasChildren && isExpanded && renderTree(item.children, depth + 1)}
        </div>
      );
    });
  };

  const getPanelColor = (node) => {
    if (isNodeHighlighted(node)) return GOLD;
    if (node.node_type === 'domain' && !['note', 'project'].includes(graphDomain)) {
      return domainColorById[node.id] || getNodeRenderProfile(node).color;
    }
    return getNodeRenderProfile(node).color;
  };

  const detailNode = selectedNode || hoveredNode;
  const handleMemorySliceClick = useCallback((node) => {
    setHoveredNode(null);
    setHoverCardPosition(null);
    setPinnedCardPosition(getNodeCardPosition(node));
    setSelectionCardVisible(true);
    setSelectedNode(node);
    loadProjectChildren(node);
    if (node.article_path) fetchArticle(node);
  }, [fetchArticle, getNodeCardPosition, loadProjectChildren]);
  const openMemoryFocus = useCallback((node, event) => {
    const source = event?.currentTarget?.getBoundingClientRect?.();
    const host = memoryWorkbenchRef.current?.getBoundingClientRect?.();
    if (source && host) setFocusOrigin({
      x: source.left + source.width / 2 - (host.left + host.width / 2),
      y: source.top + source.height / 2 - (host.top + host.height / 2),
      scale: Math.max(.32, Math.min(.72, source.width / 430)),
      rotate: ((node.id.length % 7) - 3) * .7,
    });
    setHoveredNode(null); setHoverCardPosition(null);
    handleMemorySliceClick(node); setFocusedMemoryId(node.id);
  }, [handleMemorySliceClick]);
  const memoryWorkbenchLanes = useMemo(() => {
    const lanes = { fact: [], decision: [], active: [], change: [] };
    if (graphDomain !== 'memory') return lanes;
    graphData.nodes
      .filter((node) => node.original_node_type === 'memory_point')
      .filter((node) => memoryAgentFilter === 'all' || (node.payload?.origin_client || 'personal_agent') === memoryAgentFilter)
      .filter((node) => {
        const query = memoryWorkbenchQuery.trim().toLocaleLowerCase();
        if (!query) return true;
        return `${node.label || ''} ${node.description || ''} ${node.payload?.content || ''} ${node.payload?.summary || ''} ${(node.payload?.topics || []).join(' ')}`
          .toLocaleLowerCase().includes(query);
      })
      .forEach((node) => {
        const type = node.payload?.memory_type || 'fact';
        const status = node.payload?.status || 'active';
        const target = status === 'superseded' || status === 'conflicted'
          ? 'change'
          : type === 'decision' ? 'decision'
            : type === 'goal' ? 'active' : 'fact';
        lanes[target].push(node);
      });
    Object.values(lanes).forEach((items) => items.sort((a, b) => String(b.payload?.created_at || '').localeCompare(String(a.payload?.created_at || ''))));
    return lanes;
  }, [graphData.nodes, graphDomain, memoryAgentFilter, memoryWorkbenchQuery]);
  const memoryAgentOptions = useMemo(() => {
    const clients = [...new Set(graphData.nodes.filter((node) => node.original_node_type === 'memory_point').map((node) => node.payload?.origin_client || 'personal_agent'))];
    const label = (client) => client === 'personal_agent' ? '内部对话' : client.toLowerCase() === 'codex' ? 'Codex' : client.toLowerCase() === 'workbuddy' ? 'WorkBuddy' : client;
    return [['all', '全部'], ...clients.map((client) => [client, label(client)])];
  }, [graphData.nodes]);
  const noteSearchResults = useMemo(() => {
    if (graphDomain !== 'note') return [];
    const query = noteSearchQuery.trim().toLocaleLowerCase();
    if (!query) return [];
    return graphData.nodes
      .filter((node) => `${node.label || ''} ${node.description || ''}`.toLocaleLowerCase().includes(query))
      .sort((left, right) => {
        const leftLabel = String(left.label || '').toLocaleLowerCase();
        const rightLabel = String(right.label || '').toLocaleLowerCase();
        return Number(!leftLabel.startsWith(query)) - Number(!rightLabel.startsWith(query))
          || leftLabel.localeCompare(rightLabel, 'zh-CN');
      })
      .slice(0, 10);
  }, [graphData.nodes, graphDomain, noteSearchQuery]);
  const memorySearchResults = useMemo(() => {
    if (graphDomain !== 'memory' || !memoryExpanded) return [];
    const query = memorySearchQuery.trim().toLocaleLowerCase();
    if (!query) return [];
    return graphData.nodes
      .filter((node) => `${node.label || ''} ${node.description || ''} ${node.payload?.content || ''} ${node.payload?.summary || ''} ${(node.payload?.topics || []).join(' ')}`.toLocaleLowerCase().includes(query))
      .sort((left, right) => Number(!String(left.label || '').toLocaleLowerCase().startsWith(query))
        - Number(!String(right.label || '').toLocaleLowerCase().startsWith(query)))
      .slice(0, 10);
  }, [graphData.nodes, graphDomain, memoryExpanded, memorySearchQuery]);
  const focusedMemoryNode = useMemo(() => graphData.nodes.find((node) => node.id === focusedMemoryId) || null, [focusedMemoryId, graphData.nodes]);
  const focusedMemoryRelations = useMemo(() => {
    if (!focusedMemoryNode) return [];
    const nodeById = new Map(graphData.nodes.map((node) => [node.id, node]));
    return graphData.links.flatMap((link) => {
      const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
      const targetId = typeof link.target === 'object' ? link.target.id : link.target;
      if (sourceId !== focusedMemoryNode.id && targetId !== focusedMemoryNode.id) return [];
      const other = nodeById.get(sourceId === focusedMemoryNode.id ? targetId : sourceId);
      return other?.original_node_type === 'memory_point' ? [{ node: other, relation: link.label || link.edge_type || '关联' }] : [];
    }).slice(0, 4);
  }, [focusedMemoryNode, graphData.links, graphData.nodes]);
  const memoryCandidates = useMemo(() => {
    if (!focusedMemoryNode) return [];
    const relatedIds = new Set(focusedMemoryRelations.map(({ node }) => node.id));
    const terms = (node) => {
      const text = `${node.label || ''} ${node.description || ''} ${node.payload?.content || ''} ${(node.payload?.topics || []).join(' ')}`.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
      const values = new Set();
      for (let index = 0; index < text.length - 1; index += 1) values.add(text.slice(index, index + 2));
      return values;
    };
    const sourceTerms = terms(focusedMemoryNode);
    return graphData.nodes.filter((node) => node.original_node_type === 'memory_point' && node.id !== focusedMemoryNode.id && !relatedIds.has(node.id)).map((node) => {
      const candidateTerms = terms(node); let shared = 0;
      sourceTerms.forEach((term) => { if (candidateTerms.has(term)) shared += 1; });
      return { node, score: shared / Math.sqrt(Math.max(1, sourceTerms.size * candidateTerms.size)) };
    }).filter(({ score }) => score > 0).sort((left, right) => right.score - left.score).slice(0, 5).map(({ node }) => node);
  }, [focusedMemoryNode, focusedMemoryRelations, graphData.nodes]);
  const relationLayout = [{ x: 11, y: 18, r: -3.5 }, { x: 37, y: 13, r: 2.2 }, { x: 63, y: 13, r: -2 }, { x: 89, y: 18, r: 3.5 }];
  const candidateLayout = [{ x: 9, y: 84, r: 2.5 }, { x: 29.5, y: 86, r: -3 }, { x: 50, y: 84, r: 1.8 }, { x: 70.5, y: 86, r: -2.2 }, { x: 91, y: 84, r: 3 }];
  const memoryLaneDefinitions = [
    ['fact', '事实', '可确认的信息、偏好与学习'],
    ['decision', '决定', '已经形成的选择与结论'],
    ['active', '进行中', '目标和仍在推进的事项'],
    ['change', '变化', '被修订、替代或存在冲突'],
  ];

  return (
    <div className="sf-app-container">
      {/* 视频背景覆盖整页（除顶部状态栏） */}
      <StarfieldBackground opacity={renderSettings.backgroundOpacity} />

      {/* 顶部工具栏 */}
      <header className="sf-top-bar">
        <div className="sf-top-bar-left">
          {graphDomain === 'memory' && <button
            className={`sf-toolbar-btn ${sidebarVisible ? 'active' : ''}`}
            onClick={() => setSidebarVisible(!sidebarVisible)}
            title="切换侧边栏"
          >
            {sidebarVisible ? '✕' : '☰'}
          </button>}
          <h1 className="sf-app-title">{title}</h1>
          {graphDomain === 'memory' && <button className={`sf-memory-drawer-button ${memoryWorkbenchOpen ? 'active' : ''}`} onClick={() => setMemoryWorkbenchOpen((open) => !open)}>{memoryWorkbenchOpen ? '收起记忆卡片' : '记忆卡片抽屉'}</button>}
        </div>
        <div className="sf-top-bar-center">
          <div className="sf-filter-group">
            {!memoryOriginSelector && graphDomain !== 'note' && (
              <button
                className={`sf-filter-btn ${filter === 'all' ? 'active' : ''}`}
                onClick={() => setFilter('all')}
              >全部</button>
            )}
            {!memoryOriginSelector && graphDomain === 'note' && (
              <div className="sf-note-node-search">
                <input
                  value={noteSearchQuery}
                  onChange={(event) => { setNoteSearchQuery(event.target.value); setNoteSearchOpen(true); }}
                  onFocus={() => setNoteSearchOpen(true)}
                  onBlur={() => window.setTimeout(() => setNoteSearchOpen(false), 120)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && noteSearchResults[0]) {
                      handleNodeClick(noteSearchResults[0]);
                      setNoteSearchQuery(noteSearchResults[0].label || '');
                      setNoteSearchOpen(false);
                    }
                    if (event.key === 'Escape') setNoteSearchOpen(false);
                  }}
                  placeholder="搜索主题、概念或文档"
                  aria-label="搜索笔记图谱节点"
                />
                {noteSearchOpen && noteSearchQuery.trim() && (
                  <div className="sf-note-search-results">
                    {noteSearchResults.length ? noteSearchResults.map((node) => (
                      <button key={node.id} type="button" onMouseDown={(event) => {
                        event.preventDefault();
                        setNoteSearchQuery(node.label || '');
                        setNoteSearchOpen(false);
                        handleNodeClick(node);
                      }}>
                        <span>{node.label || node.id}</span>
                        <small>{NOTE_TOPIC_TYPES.has(node.original_node_type) ? '主题' : NOTE_CONCEPT_TYPES.has(node.original_node_type) ? '概念' : '文档'}</small>
                      </button>
                    )) : <div className="sf-note-search-empty">没有匹配节点</div>}
                  </div>
                )}
              </div>
            )}
            {memoryOriginSelector && <div className="sf-memory-view-switch" role="group" aria-label="记忆视图"><button className={!memoryExpanded ? 'active' : ''} aria-pressed={!memoryExpanded} onClick={() => handleMemoryView('galaxy')}>记忆星图</button><button className={memoryExpanded ? 'active' : ''} aria-pressed={memoryExpanded} onClick={() => handleMemoryView('info')}>记忆信息</button></div>}
            {roadmapSelector && (
              <select
                className="sf-roadmap-selector"
                value={selectedRoadmapId}
                onChange={(event) => {
                  setSelectedRoadmapId(event.target.value);
                  setSelectedNode(null);
                  setArticleContent(null);
                }}
                aria-label="选择学习路线知识子图"
              >
                {!roadmapOptions.length && <option value="">暂无学习路线</option>}
                {roadmapOptions.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.plan_name}{plan.is_current ? '（当前）' : ''}
                    {plan.has_subgraph ? '' : ' · 未生成子图'}
                  </option>
                ))}
              </select>
            )}
            {!simpleMode && (
              <>
                <button
                  className={`sf-filter-btn ${filter === 'contains' ? 'active' : ''}`}
                  onClick={() => setFilter('contains')}
                >{graphDomain === 'project' ? '项目结构' : '包含关系'}</button>
                <button
                  className={`sf-filter-btn ${filter === 'related' ? 'active' : ''}`}
                  onClick={() => setFilter('related')}
                >{graphDomain === 'project' ? '模块关系' : '关联关系'}</button>
              </>
            )}
          </div>
        </div>
        <div className="sf-top-bar-right">
          {graphDomain === 'memory' && memoryExpanded && <div className="sf-memory-node-search">
            <input value={memorySearchQuery} onChange={(event) => { setMemorySearchQuery(event.target.value); setMemorySearchOpen(true); }} onFocus={() => setMemorySearchOpen(true)} onBlur={() => window.setTimeout(() => setMemorySearchOpen(false), 120)} onKeyDown={(event) => {
              if (event.key === 'Enter' && memorySearchResults[0]) { handleNodeClick(memorySearchResults[0]); setMemorySearchQuery(memorySearchResults[0].label || ''); setMemorySearchOpen(false); }
              if (event.key === 'Escape') setMemorySearchOpen(false);
            }} placeholder="搜索记忆点或实体" aria-label="搜索记忆节点" />
            {memorySearchOpen && memorySearchQuery.trim() && <div className="sf-note-search-results">{memorySearchResults.length ? memorySearchResults.map((node) => <button key={node.id} type="button" onMouseDown={(event) => { event.preventDefault(); setMemorySearchQuery(node.label || ''); setMemorySearchOpen(false); handleNodeClick(node); }}><span>{node.label || node.id}</span><small>{node.original_node_type === 'memory_entity' ? '实体' : '记忆点'}</small></button>) : <div className="sf-note-search-empty">没有匹配节点</div>}</div>}
          </div>}
          {memoryOriginSelector && (
            <button className="sf-watcher-toggle" onClick={() => {
              setHistoryOpen(true); setHistoryClient(''); setHistorySessions([]); setHistorySelectedSession(null); setHistoryPreview(null); setHistoryMessage('');
            }}>导入历史</button>
          )}
          {!simpleMode && !freeScatter && graphDomain !== 'project' && (
            <button
              className={`sf-toolbar-btn ${viewMode === 'galaxy' ? 'active' : ''}`}
              onClick={handleToggleView}
              title={viewMode === 'clusters' ? '切换到单球总览视图' : '切回分域星图'}
            >
              {viewMode === 'clusters' ? '🌐 总览' : '🔭 分域'}
            </button>
          )}
          {loading && <span className="sf-loading-text">加载中...</span>}
          {!(memoryOriginSelector && !memoryExpanded) && <span className="sf-stats-text">
            {displayedGraphData.nodes.length} 星点 · {displayedGraphData.links.length} 星轨
          </span>}
        </div>
      </header>

      <div className="sf-main-content">
        {/* 左侧边栏 - 完全透明，真实知识库目录 */}
        {graphDomain === 'memory' && <aside className={`sf-sidebar ${sidebarVisible ? 'visible' : 'hidden'}`} style={{ width: sidebarWidth }}>
          <div className="sf-sidebar-header">
            <h3>{directoryTitle}</h3>
          </div>
          <div className="sf-sidebar-tree">
            {renderTree(fileTree)}
          </div>
          <div className="sf-sidebar-resizer" role="separator" aria-label="调整目录宽度" onPointerDown={startSidebarResize}/>
        </aside>}

        {/* 图谱画布 */}
        <main className="sf-graph-canvas">
          {loading ? (
            <div className="sf-loading-overlay">
              <div className="sf-spinner"></div>
              <p>点亮知识星图...</p>
            </div>
          ) : graphError ? (
            <div className="sf-loading-overlay">
              <p>{graphError}</p>
            </div>
          ) : (
            <div
              id="fg3d-container"
              className={selectedNode ? 'sf-fixed-label-mode' : ''}
              ref={graphContainerRef}
              style={{ width: '100%', height: '100%', minHeight: 400, position: 'relative' }}
            >
              {graphSize.width > 0 && graphSize.height > 0 && <ForceGraph3D
                ref={fgRef}
                width={graphSize.width}
                height={graphSize.height}
                graphData={renderedGraphData}
                nodeThreeObject={nodeThreeObject}
                nodeLabel={NO_NODE_LABEL}
                linkColor={linkColor}
                linkVisibility={linkVisibility}
                linkOpacity={memoryClustered
                  ? renderSettings.memoryClusterLineOpacity
                  : renderSettings.lineOpacity}
                linkWidth={linkWidth}
                linkCurvature={link => graphDomain === 'memory' ? 0.12 + stableUnit(`${typeof link.source === 'object' ? link.source.id : link.source}:${typeof link.target === 'object' ? link.target.id : link.target}`, 907) * 0.12 : 0}
                linkCurveRotation={link => stableUnit(`${typeof link.source === 'object' ? link.source.id : link.source}:${typeof link.target === 'object' ? link.target.id : link.target}`, 919) * Math.PI * 2}
                linkDirectionalParticles={link => graphDomain === 'memory' && selectedNode && linkVisibility(link) ? 3 : 0}
                linkDirectionalParticleWidth={2.8}
                linkDirectionalParticleColor={() => '#d9ccff'}
                linkDirectionalParticleSpeed={relationParticleSpeed}
                linkDirectionalArrowLength={link => link.edge_type === 'imports' ? 4 : 0}
                linkDirectionalArrowRelPos={1}
                linkDirectionalArrowColor={link => link.edge_type === 'imports'
                  ? 'rgba(183,140,255,0.72)'
                  : 'rgba(0,0,0,0)'}
                enableNodeDrag={!selectedNode}
                onNodeClick={handleNodeClick}
                onNodeHover={handleNodeHover}
                onBackgroundClick={handleBackgroundClick}
                showNavInfo={false}
                backgroundColor="rgba(0,0,0,0)"
                cooldownTicks={graphDomain === 'memory' ? 0 : 220}
                d3AlphaDecay={0.018}
                d3VelocityDecay={0.32}
                warmupTicks={graphDomain === 'memory' ? 0 : 40}
                nodeRelSize={1}
                minZoom={0.5}
                maxZoom={2000}
                numDimensions={3}
                controlType="orbit"
                onEngineStop={() => {
                  if (import.meta.env.DEV && fgRef.current) window.__fg3d = fgRef.current;
                }}
              />}
            </div>
          )}

          {/* 选中节点详情面板（单击节点即弹出，固定在画布左下角） */}
          {detailNode && !focusedMemoryNode && (!selectedNode || selectionCardVisible) && (
            <div
              className={`sf-node-detail-panel ${selectedNode ? 'pinned' : 'hover-preview'}`}
              style={(selectedNode ? pinnedCardPosition : hoverCardPosition) ? {
                left: `${(selectedNode ? pinnedCardPosition : hoverCardPosition).x}px`,
                top: `${(selectedNode ? pinnedCardPosition : hoverCardPosition).y}px`,
                right: 'auto',
                bottom: 'auto',
              } : undefined}
            >
              <div className="sf-panel-header">
                <span
                  className="sf-panel-color"
                  style={{ background: getPanelColor(detailNode), color: getPanelColor(detailNode) }}
                ></span>
                <h3>{detailNode.label || detailNode.id}</h3>
                {selectedNode && <button
                  className="sf-panel-close"
                  aria-label="关闭简介卡片（保留节点选中）"
                  onClick={() => { setSelectionCardVisible(false); setPinnedCardPosition(null); setShowArticle(false); }}
                >×</button>}
              </div>
              <div className="sf-panel-body">
                {/* 元信息标签：类型 / 领域 / 掌握度 */}
                <div className="sf-panel-meta">
                  <span className="sf-meta-tag">
                    {actualNodeTypeIcon(detailNode, graphDomain)} {actualNodeTypeLabel(detailNode, graphDomain)}
                  </span>
                  {detailNode.domain && (
                    <span className="sf-meta-tag">{detailNode.domain}</span>
                  )}
                  {detailNode.mastery_level && (
                    <span className={`sf-meta-tag ${detailNode.is_learned ? 'learned' : ''}`}>
                      {detailNode.mastery_level}
                    </span>
                  )}
                </div>

                {detailNode.description && (
                  <p className="sf-panel-desc">{detailNode.description}</p>
                )}

                {/* 外部链接（如果有） */}
                {Array.isArray(detailNode.external_links) && detailNode.external_links.length > 0 && (
                  <div className="sf-panel-links">
                    <h4>外部链接</h4>
                    {detailNode.external_links.map((link, i) => (
                      <a key={i} href={link.url} target="_blank" rel="noopener noreferrer">
                        {link.title || link.url}
                      </a>
                    ))}
                  </div>
                )}

                {/* 阅读文章；个人文档改为跳转笔记工作区并打开源文档。 */}
                {detailNode.article_path ? (
                  <button
                    className="sf-panel-read-btn"
                    onClick={() => loadArticle(detailNode)}
                    disabled={articleLoading}
                  >
                    {articleLoading
                      ? '加载中…'
                      : (graphDomain === 'memory' && detailNode.payload?.turn_id
                          ? '📖 显示原文'
                          : '📖 阅读内容')}
                  </button>
                ) : graphDomain === 'note' && detailNode.original_node_type?.startsWith('wiki_') && detailNode.payload?.page_id && onOpenWikiPage ? (
                  <div className="sf-panel-read-actions">
                    <button className="sf-panel-read-btn" onClick={() => onOpenWikiPage(detailNode.payload.page_id)}>
                      📖 在 Wiki 中阅读
                    </button>
                    <button className="sf-panel-read-btn" onClick={() => loadArticle(detailNode)} disabled={articleLoading}>
                      {articleLoading ? '加载中…' : '▤ 当前页面查看'}
                    </button>
                  </div>
                ) : graphDomain === 'note' && detailNode.original_node_type === 'document' && detailNode.payload?.document_id && onOpenLibraryDocument ? (
                  <button
                    className="sf-panel-read-btn"
                    onClick={() => onOpenLibraryDocument(detailNode.payload.document_id)}
                  >
                    📖 阅读文章
                  </button>
                ) : (
                  <p className="sf-detail-noarticle">该节点暂无关联文章</p>
                )}

                {detailNode.is_learned && (
                  <div className="sf-detail-learned">
                    ✦ 已学习 · 掌握度 {Math.round(detailNode.mastery_score || 0)}%
                  </div>
                )}
              </div>
            </div>
          )}

          {graphDomain === 'memory' && memoryWorkbenchOpen && <section ref={memoryWorkbenchRef} className={`sf-memory-workbench ${focusedMemoryNode ? 'focus-active' : ''}`} aria-label="记忆地层台">
            <header><div className="sf-memory-workbench-title"><h2>记忆抽屉</h2><p>从事实、决定、进行中和变化四个抽屉快速查阅长期记忆</p></div><div className="sf-memory-workbench-tools"><nav className="sf-memory-agent-filters" aria-label="按智能体筛选记忆">{memoryAgentOptions.map(([value, label]) => <button type="button" className={memoryAgentFilter === value ? 'active' : ''} aria-pressed={memoryAgentFilter === value} onClick={() => { setMemoryAgentFilter(value); setFocusedMemoryId(''); }} key={value}><i/>{label}</button>)}</nav><label className="sf-memory-workbench-search"><span>⌕</span><input value={memoryWorkbenchQuery} onChange={(event) => { setMemoryWorkbenchQuery(event.target.value); setFocusedMemoryId(''); }} placeholder="搜索四个抽屉中的记忆" /></label><button className="sf-memory-workbench-close" type="button" aria-label="关闭记忆抽屉" onClick={() => setMemoryWorkbenchOpen(false)}>×</button></div></header>
            <div className="sf-memory-lanes">
              {memoryLaneDefinitions.map(([key, label, description]) => <section className={`sf-memory-lane lane-${key}`} key={key}><header><div><i/><strong>{label}</strong></div><span>{memoryWorkbenchLanes[key].length}</span><p>{description}</p></header><div className="sf-memory-drawer">{memoryWorkbenchLanes[key].length ? memoryWorkbenchLanes[key].map((node, index) => <button type="button" style={{ '--stack-index': index }} className={`sf-memory-slice ${node.payload?.status || 'active'} ${selectedNode?.id === node.id ? 'selected' : ''}`} key={node.id} onClick={(event) => openMemoryFocus(node, event)}><small><time>{node.payload?.created_at ? new Date(node.payload.created_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : memoryTypeLabel(node.payload?.memory_type)}</time><b>{node.payload?.origin_client || '内部对话'}</b></small><strong>{node.label || node.payload?.summary || '长期记忆'}</strong><p>{node.description || node.payload?.content || node.payload?.summary || '暂无内容摘要'}</p></button>) : <p className="sf-memory-lane-empty">暂无此类记忆</p>}</div></section>)}
            </div>
            <footer><span>{selectedNode ? `已定位：${selectedNode.label || selectedNode.id}` : '点击任意记忆切片，背后的星图会同步高亮对应节点'}</span><button type="button" disabled={!selectedNode} onClick={() => setMemoryWorkbenchOpen(false)}>查看星图定位</button></footer>
            {focusedMemoryNode && <div className="sf-memory-focus-space" onClick={() => setFocusedMemoryId('')}>
              <div className="sf-memory-focus-haze"/>
              <div className="sf-memory-orbit" onClick={(event) => event.stopPropagation()}>
                <button type="button" className="sf-memory-focus-close" aria-label="关闭关联聚焦" onClick={() => setFocusedMemoryId('')}>×</button>
                {focusRelationsVisible && <div className="sf-memory-relation-legend" aria-label="关系类型图例"><span><i className="candidate"/>可能相关</span><span><i className="explicit"/>明确关联</span></div>}
                {focusRelationsVisible && <svg className="sf-memory-connection-field" viewBox="0 0 920 590" preserveAspectRatio="none" aria-hidden="true">{focusedMemoryRelations.flatMap((item, index) => [<line className="explicit" x1="460" y1="295" x2={relationLayout[index].x * 9.2} y2={relationLayout[index].y * 5.9} key={`line-${item.node.id}`}/>, <line className="explicit signal" x1="460" y1="295" x2={relationLayout[index].x * 9.2} y2={relationLayout[index].y * 5.9} key={`signal-${item.node.id}`}/>])}{memoryCandidates.flatMap((node, index) => [<line className="candidate" x1="460" y1="295" x2={candidateLayout[index].x * 9.2} y2={candidateLayout[index].y * 5.9} key={`candidate-line-${node.id}`}/>, <line className="candidate signal" x1="460" y1="295" x2={candidateLayout[index].x * 9.2} y2={candidateLayout[index].y * 5.9} key={`candidate-signal-${node.id}`}/>])}</svg>}
                <article className="sf-memory-focus-card" style={{ '--flight-x': `${focusOrigin.x}px`, '--flight-y': `${focusOrigin.y}px`, '--flight-scale': focusOrigin.scale, '--flight-rotate': `${focusOrigin.rotate}deg` }}><small>{memoryTypeLabel(focusedMemoryNode.payload?.memory_type)} · {focusedMemoryNode.payload?.origin_client || '内部对话'}</small><h3>{focusedMemoryNode.label || focusedMemoryNode.payload?.summary || '长期记忆'}</h3><p>{focusedMemoryNode.description || focusedMemoryNode.payload?.content || '暂无内容摘要'}</p></article>
                {focusRelationsVisible && focusedMemoryRelations.map(({ node, relation }, index) => <button type="button" className="sf-memory-related-card explicit" style={{ '--card-x': `${relationLayout[index].x}%`, '--card-y': `${relationLayout[index].y}%`, '--card-rotate': `${relationLayout[index].r}deg`, '--reveal-index': index }} key={node.id} onClick={(event) => openMemoryFocus(node, event)}><small>{relation} · {memoryTypeLabel(node.payload?.memory_type)}</small><strong>{node.label || node.payload?.summary || '关联记忆'}</strong></button>)}
                {focusRelationsVisible && memoryCandidates.map((node, index) => <button type="button" className="sf-memory-related-card candidate" style={{ '--card-x': `${candidateLayout[index].x}%`, '--card-y': `${candidateLayout[index].y}%`, '--card-rotate': `${candidateLayout[index].r}deg`, '--reveal-index': index }} key={`candidate-${node.id}`} onClick={(event) => openMemoryFocus(node, event)}><small>{memoryTypeLabel(node.payload?.memory_type)} · {node.payload?.origin_client || '内部对话'}</small><strong>{node.label || node.payload?.summary || '相关记忆'}</strong></button>)}
              </div>
            </div>}
          </section>}
        </main>
        {deleteSessionTarget && <div className="sf-delete-confirm-backdrop" onMouseDown={() => setDeleteSessionTarget(null)}><section className="sf-delete-confirm" onMouseDown={(event) => event.stopPropagation()}><h3>{deleteSessionTarget.original_node_type === 'conversation_turn' ? '删除这条对话？' : '删除整段会话？'}</h3><p>“{deleteSessionTarget.label}”及其产生的记忆点、关联关系都会从本地删除，此操作无法撤销。</p><label><input type="checkbox" checked={rememberDeleteChoice} onChange={(event) => setRememberDeleteChoice(event.target.checked)}/>以后删除时不再询问</label><footer><button type="button" className="cancel" onClick={() => setDeleteSessionTarget(null)}>取消</button><button type="button" className="danger" onClick={() => { if (rememberDeleteChoice) localStorage.setItem('personal-agent:skip-memory-delete-confirm', 'true'); deleteMemorySession(deleteSessionTarget); }}>确认删除</button></footer></section></div>}

        {/* 右侧文章阅读面板（点击“阅读文章”后滑出） */}
        {showArticle && articleContent && (
          <aside className="sf-article-panel">
            <div className="sf-article-header">
              <h3>{selectedNode?.label || selectedNode?.id || '文章内容'}</h3>
              <button className="sf-panel-close" onClick={() => setShowArticle(false)}>×</button>
            </div>
            <div className="sf-article-body">
              {articleContent.view === 'conversation' ? (
                <div className="sf-memory-conversation-reader">
                  <header><strong>{articleContent.title}</strong><small>{articleContent.source} · {articleContent.createdAt}</small></header>
                  {articleContent.summary && <section className="sf-conversation-summary"><strong>对话概括</strong><p>{articleContent.summary}</p></section>}
                  <section className="sf-conversation-turn"><div className="sf-conversation-bubble user"><b>问题</b><div className="sf-conversation-markdown"><MarkdownRenderer content={articleContent.userMessage} /></div></div><div className="sf-conversation-bubble assistant"><b>回答</b><div className="sf-conversation-markdown"><MarkdownRenderer content={articleContent.assistantMessage} /></div></div></section>
                </div>
              ) : articleContent.content ? (
                <div className="sf-article-markdown">
                  <MarkdownRenderer content={articleContent.content} onNavigateWiki={onOpenWikiPage} onNavigateDocument={onOpenLibraryDocument} onNavigateNote={onOpenLibraryNote} />
                </div>
              ) : (
                <p>暂无内容</p>
              )}
              {articleContent.sourceDocumentId && (
                <button className="sf-article-source-link" onClick={() => onOpenLibraryDocument?.(articleContent.sourceDocumentId)}>
                  打开源文档 →
                </button>
              )}
              {articleContent.wikiPageId && (
                <button className="sf-article-source-link" onClick={() => onOpenWikiPage?.(articleContent.wikiPageId)}>
                  在 Wiki 中阅读原文 →
                </button>
              )}
            </div>
          </aside>
        )}

        <button
          className={`sf-render-settings-tab ${renderSettingsOpen ? 'open' : ''}`}
          onClick={() => {
            setRenderSettingsDraft({ ...renderSettings });
            setRenderSettingsOpen((open) => !open);
          }}
          title={renderSettingsOpen ? '收起个性化设置' : '打开个性化设置'}
          aria-label={renderSettingsOpen ? '收起个性化设置' : '打开个性化设置'}
        >
          ⚙
        </button>
        <aside
          className={`sf-render-settings-drawer ${renderSettingsOpen ? 'open' : ''}`}
        >
          <header>
            <div><strong>个性化设置</strong><p>保存后立即重新渲染，并保留到本机。</p></div>
          </header>
          <div className="sf-render-settings-body">
            {graphDomain === 'memory' ? (
              <>
                {!memoryExpanded ? (
                  <section className="sf-render-always"><label>粒子量级 <select value={renderSettingsDraft.memoryGalaxyParticleLevel} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, memoryGalaxyParticleLevel: Number(event.target.value) })}><option value={0.25}>25%</option><option value={0.5}>50%</option><option value={0.75}>75%</option><option value={1}>100%</option></select></label><label>转速 <output>{Math.round(renderSettingsDraft.memoryGalaxyRotationSpeed * 100)}%</output><input type="range" min="0" max="1.5" step="0.05" value={renderSettingsDraft.memoryGalaxyRotationSpeed} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, memoryGalaxyRotationSpeed: Number(event.target.value) })} /></label><label>闪烁强度 <output>{Math.round(renderSettingsDraft.memoryGalaxyShimmerStrength * 100)}%</output><input type="range" min="0" max="4" step="0.05" value={renderSettingsDraft.memoryGalaxyShimmerStrength} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, memoryGalaxyShimmerStrength: Number(event.target.value) })} /></label></section>
                ) : null}
                {!memoryExpanded ? (
                  <details className="sf-render-card"><summary>银河星点 · 对话记忆 <span>›</span></summary><div><label>大小 <output>{Math.round(renderSettingsDraft.memoryPrimarySize * 100)}%</output><input type="range" min="0.5" max="1.65" step="0.05" value={Math.min(1.65, renderSettingsDraft.memoryPrimarySize)} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, memoryPrimarySize: Number(event.target.value) })} /></label><label>亮度 <output>{Math.round(renderSettingsDraft.memoryPrimaryBrightness * 100)}%</output><input type="range" min="0.5" max="2" step="0.05" value={renderSettingsDraft.memoryPrimaryBrightness} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, memoryPrimaryBrightness: Number(event.target.value) })} /></label>{[['memoryInternalColor','内部记忆'],['memoryAgent1Color','智能体 1'],['memoryAgent2Color','智能体 2'],['memoryAgent3Color','智能体 3']].map(([key,label]) => <label key={key}>{label}<input type="color" value={renderSettingsDraft[key]} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, [key]: event.target.value })} /></label>)}</div></details>
                ) : (
                  <>
                    {memoryClustered ? (
                      <>
                        <label className="sf-render-standalone-slider">空间大小 <output>{Math.round(renderSettingsDraft.memoryClusterSpatialScale * 100)}%</output><input type="range" min="0.5" max="2" step="0.05" value={renderSettingsDraft.memoryClusterSpatialScale} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, memoryClusterSpatialScale: Number(event.target.value) })} /></label>
                        <label className="sf-render-standalone-slider">整体自转 <output>{Math.round(renderSettingsDraft.memoryClusterRotationSpeed * 100)}%</output><input type="range" min="0" max="1" step="0.02" value={renderSettingsDraft.memoryClusterRotationSpeed} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, memoryClusterRotationSpeed: Number(event.target.value) })} /></label>
                        <label className="sf-render-cluster-links-toggle"><span><input type="checkbox" checked={renderSettingsDraft.memoryClusterShowLinks} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, memoryClusterShowLinks: event.target.checked })} />展示所有关联线</span><small>为了防止卡顿，打开关联线展示之后，会停止转动。</small></label>
                      </>
                    ) : (
                      <>
                        <label className="sf-render-standalone-slider">空间大小 <output>{Math.round(renderSettingsDraft.memorySpatialScale * 100)}%</output><input type="range" min="0.5" max="2" step="0.05" value={renderSettingsDraft.memorySpatialScale} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, memorySpatialScale: Number(event.target.value) })} /></label>
                        <label className="sf-render-standalone-slider">移动速度 <output>{Math.round(renderSettingsDraft.memoryMovementSpeed * 100)}%</output><input type="range" min="0" max="5" step="0.05" value={renderSettingsDraft.memoryMovementSpeed} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, memoryMovementSpeed: Number(event.target.value) })} /></label>
                      </>
                    )}
                    {renderExpandedMemoryStyleCards(memoryClustered)}
                  </>
                )}
              </>
            ) : graphDomain === 'note' ? (
              <>
                {renderNoteStyleSection('主题星点', 'noteTopic')}
                {renderNoteStyleSection('概念星点', 'noteConcept')}
                {renderNoteStyleSection('文档星点', 'noteDocument')}
              </>
            ) : graphDomain === 'project' ? (
              <>
                {renderNodeStyleSection('代码块 · 函数与方法', 'projectBlock')}
                {renderNodeStyleSection('其他节点 · 项目、目录与文件', 'projectOther')}
              </>
            ) : renderNodeStyleSection('全部星点', 'general')}
            {!(graphDomain === 'memory' && !memoryExpanded) && <details className="sf-render-card"><summary>空间布局 <span>›</span></summary><div>
              <label>聚拢程度 <output>{renderSettingsDraft.clustering.toFixed(1)}×</output><input type="range" min="0.5" max="2" step="0.1" value={renderSettingsDraft.clustering} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, clustering: Number(event.target.value) })} /></label>
              <label>关系线颜色<input type="color" value={memoryClustered ? renderSettingsDraft.memoryClusterLineColor : renderSettingsDraft.lineColor} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, [memoryClustered ? 'memoryClusterLineColor' : 'lineColor']: event.target.value })} /></label>
              <label>关系线亮度 <output>{Math.round((memoryClustered ? renderSettingsDraft.memoryClusterLineOpacity : renderSettingsDraft.lineOpacity) * 100)}%</output><input type="range" min="0.05" max="1" step="0.05" value={memoryClustered ? renderSettingsDraft.memoryClusterLineOpacity : renderSettingsDraft.lineOpacity} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, [memoryClustered ? 'memoryClusterLineOpacity' : 'lineOpacity']: Number(event.target.value) })} /></label>
              <label>关系线粗度 <output>{Math.round((memoryClustered ? renderSettingsDraft.memoryClusterLineThickness : renderSettingsDraft.lineThickness) * 100)}%</output><input type="range" min="0.5" max="6" step="0.05" value={memoryClustered ? renderSettingsDraft.memoryClusterLineThickness : renderSettingsDraft.lineThickness} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, [memoryClustered ? 'memoryClusterLineThickness' : 'lineThickness']: Number(event.target.value) })} /></label>
              <label>背景星空亮度 <output>{Math.round(renderSettingsDraft.backgroundOpacity * 100)}%</output><input type="range" min="0.15" max="1" step="0.05" value={renderSettingsDraft.backgroundOpacity} onChange={(event) => setRenderSettingsDraft({ ...renderSettingsDraft, backgroundOpacity: Number(event.target.value) })} /></label>
            </div></details>}
          </div>
          <footer><button onClick={handleResetRenderSettings}>恢复默认</button><button className="primary" onClick={handleSaveRenderSettings}>保存设置</button></footer>
        </aside>
      </div>
      {historyOpen && (
        <div className="sf-history-backdrop" onMouseDown={() => setHistoryOpen(false)}>
          <section className="sf-history-dialog" onMouseDown={(event) => event.stopPropagation()}>
            <header><div><strong>导入外部历史会话</strong><p>先选择来源和会话，再查询最近 20 轮内容；重复导入不会产生重复星点。</p></div>
              <button onClick={() => setHistoryOpen(false)}>×</button></header>
            <div className="sf-history-toolbar">
              <select value={historyClient} onChange={(event) => {
                const client = event.target.value; setHistoryClient(client); setHistorySessions([]); setHistorySelectedSession(null); setHistoryPreview(null); setHistoryMessage(''); if (client) loadHistorySessions(client);
              }}><option value="">选择已启用的智能体</option>{(watcherStatus?.watchers || []).filter((watcher) => watcher.enabled).map((watcher) => <option key={watcher.id} value={watcher.id}>{watcher.name}</option>)}</select>
              {historyClient && <button onClick={() => loadHistorySessions(historyClient)}>刷新会话</button>}
              {historySelectedSession && <button className="primary" onClick={previewHistorySession} disabled={historyLoading}>查询对话</button>}
            </div>
            {historyMessage && <p className="sf-history-message">{historyMessage}</p>}
            {!historyClient && <div className="sf-history-empty">{(watcherStatus?.watchers || []).some((watcher) => watcher.enabled) ? '请选择需要导入的来源智能体。' : '暂无已配置并启用的智能体，请先到设置 · 智能体监听中添加并启用。'}</div>}
            {historyClient && !historyPreview && <div className="sf-history-list">
              {historyLoading && !historySessions.length ? <p>正在扫描历史会话…</p> : historySessions.map((session) => (
                <article className={historySelectedSession?.session_id === session.session_id ? 'selected' : ''} key={`${session.client}:${session.session_id}`} onClick={() => { setHistorySelectedSession(session); setHistoryMessage(''); }}>
                  <div><strong>{session.title}</strong><p>{session.turn_count} 轮 · {new Date(session.updated_at).toLocaleString()}</p><small>{session.cwd || session.transcript_path}</small></div>
                </article>
              ))}
              {!historyLoading && !historySessions.length && <p>没有发现可导入的会话。</p>}
            </div>}
            {historyPreview && <div className="sf-history-preview">
              <div className="sf-history-preview-heading"><button onClick={() => { setHistoryPreview(null); setHistoryMessage(''); }}>← 返回会话</button><strong>{historySelectedSession?.title}</strong><button className="primary" onClick={() => importHistorySession(historySelectedSession)} disabled={historyLoading}>导入整段会话</button></div>
              <div className="sf-history-turns">{historyPreview.turns.map((turn, index) => <article key={turn.turn_id || index}><span>第 {historyPreview.turn_count - historyPreview.turns.length + index + 1} 轮</span><div className="sf-history-bubble user"><b>问题</b><div className="sf-conversation-markdown"><MarkdownRenderer content={turn.user_message} /></div></div><div className="sf-history-bubble assistant"><b>回答</b><div className="sf-conversation-markdown"><MarkdownRenderer content={turn.assistant_message} /></div></div></article>)}</div>
            </div>}
          </section>
        </div>
      )}
    </div>
  );
}

// ====================================================================
//  工具：生成径向渐变光晕贴图（Three.js Sprite 用）
// ====================================================================

const HALO_TEXTURE_CACHE = new Map();

function makeHaloTexture(colorHex, glowStyle = 'soft') {
  const cacheKey = `${colorHex}:${glowStyle}`;
  if (HALO_TEXTURE_CACHE.has(cacheKey)) return HALO_TEXTURE_CACHE.get(cacheKey);
  const rgb = hexToRgb(colorHex);
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  if (glowStyle === 'halo') {
    grad.addColorStop(0, `rgba(${rgb.r},${rgb.g},${rgb.b},0.12)`);
    grad.addColorStop(0.28, `rgba(${rgb.r},${rgb.g},${rgb.b},0.24)`);
    grad.addColorStop(0.48, `rgba(${rgb.r},${rgb.g},${rgb.b},0.78)`);
    grad.addColorStop(0.67, `rgba(${rgb.r},${rgb.g},${rgb.b},0.12)`);
  } else if (glowStyle === 'compact') {
    grad.addColorStop(0, `rgba(${rgb.r},${rgb.g},${rgb.b},0.95)`);
    grad.addColorStop(0.12, `rgba(${rgb.r},${rgb.g},${rgb.b},0.68)`);
    grad.addColorStop(0.3, `rgba(${rgb.r},${rgb.g},${rgb.b},0.14)`);
    grad.addColorStop(0.52, `rgba(${rgb.r},${rgb.g},${rgb.b},0.02)`);
  } else if (glowStyle === 'note-dense') {
    grad.addColorStop(0, `rgba(${rgb.r},${rgb.g},${rgb.b},0.98)`);
    grad.addColorStop(0.12, `rgba(${rgb.r},${rgb.g},${rgb.b},0.92)`);
    grad.addColorStop(0.28, `rgba(${rgb.r},${rgb.g},${rgb.b},0.74)`);
    grad.addColorStop(0.48, `rgba(${rgb.r},${rgb.g},${rgb.b},0.43)`);
    grad.addColorStop(0.70, `rgba(${rgb.r},${rgb.g},${rgb.b},0.14)`);
    grad.addColorStop(0.86, `rgba(${rgb.r},${rgb.g},${rgb.b},0.035)`);
  } else {
    grad.addColorStop(0, `rgba(${rgb.r},${rgb.g},${rgb.b},0.9)`);
    grad.addColorStop(0.15, `rgba(${rgb.r},${rgb.g},${rgb.b},0.55)`);
    grad.addColorStop(0.45, `rgba(${rgb.r},${rgb.g},${rgb.b},0.18)`);
  }
  grad.addColorStop(1, `rgba(${rgb.r},${rgb.g},${rgb.b},0)`);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  HALO_TEXTURE_CACHE.set(cacheKey, tex);
  return tex;
}

// 亮核贴图：白色中心 → 节点色 → 透明，给模糊光点一个"点"的锚定感
const CORE_TEXTURE_CACHE = new Map();
const STAR_FLARE_TEXTURE_CACHE = new Map();
function makeCoreTexture(colorHex) {
  if (CORE_TEXTURE_CACHE.has(colorHex)) return CORE_TEXTURE_CACHE.get(colorHex);
  const rgb = hexToRgb(colorHex);
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(0.25, `rgba(${rgb.r},${rgb.g},${rgb.b},0.95)`);
  grad.addColorStop(0.6, `rgba(${rgb.r},${rgb.g},${rgb.b},0.35)`);
  grad.addColorStop(1, `rgba(${rgb.r},${rgb.g},${rgb.b},0)`);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  CORE_TEXTURE_CACHE.set(colorHex, tex);
  return tex;
}

function makeStarFlareTexture(colorHex) {
  if (STAR_FLARE_TEXTURE_CACHE.has(colorHex)) return STAR_FLARE_TEXTURE_CACHE.get(colorHex);
  const rgb = hexToRgb(colorHex);
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const center = size / 2;
  ctx.shadowColor = `rgba(${rgb.r},${rgb.g},${rgb.b},.9)`;
  ctx.shadowBlur = 9;
  const diamond = ctx.createRadialGradient(center, center, 1, center, center, center);
  diamond.addColorStop(0, 'rgba(255,255,255,.98)');
  diamond.addColorStop(.22, `rgba(${rgb.r},${rgb.g},${rgb.b},.82)`);
  diamond.addColorStop(.62, `rgba(${rgb.r},${rgb.g},${rgb.b},.18)`);
  diamond.addColorStop(1, `rgba(${rgb.r},${rgb.g},${rgb.b},0)`);
  ctx.fillStyle = diamond;
  ctx.beginPath();
  ctx.moveTo(center, 8);
  ctx.lineTo(center + 8, center - 8);
  ctx.lineTo(size - 8, center);
  ctx.lineTo(center + 8, center + 8);
  ctx.lineTo(center, size - 8);
  ctx.lineTo(center - 8, center + 8);
  ctx.lineTo(8, center);
  ctx.lineTo(center - 8, center - 8);
  ctx.closePath();
  ctx.fill();
  const texture = new THREE.CanvasTexture(canvas);
  STAR_FLARE_TEXTURE_CACHE.set(colorHex, texture);
  return texture;
}

// 名称标签精灵：把节点名画到 canvas 上，做成始终朝向相机的 Sprite。
// 用于「选中/关联节点常驻显示名称」，depthTest:false 保证浮在最上层可见。
function makeTextSprite(text, colorHex, radius) {
  const characters = Array.from(String(text || ''));
  const displayText = characters.length > 24 ? `${characters.slice(0, 23).join('')}…` : characters.join('');
  const fontSize = 46;
  const pad = 18;
  const font = `600 ${fontSize}px "PingFang SC","Microsoft YaHei",sans-serif`;
  const canvas = document.createElement('canvas');
  let ctx = canvas.getContext('2d');
  ctx.font = font;
  const tw = Math.ceil(ctx.measureText(displayText).width);
  const w = tw + pad * 2;
  const h = fontSize + pad * 2;
  canvas.width = w;
  canvas.height = h;
  ctx = canvas.getContext('2d');
  ctx.font = font;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  // 两层填充：先大模糊光晕，再实心核心，模拟发光文字
  ctx.shadowColor = colorHex;
  ctx.shadowBlur = 16;
  ctx.fillStyle = colorHex;
  ctx.fillText(displayText, w / 2, h / 2);
  ctx.shadowBlur = 5;
  ctx.fillStyle = '#ffffff';
  ctx.globalAlpha = 0.85;
  ctx.fillText(displayText, w / 2, h / 2);

  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  tex.needsUpdate = true;
  tex.generateMipmaps = false;
  tex.magFilter = THREE.LinearFilter;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false, toneMapped: false });
  const sprite = new THREE.Sprite(mat);
  sprite.frustumCulled = false;
  sprite.renderOrder = 10000;
  const pixelHeight = 26;
  const aspect = w / h;
  const worldPosition = new THREE.Vector3();
  // 游戏 HUD / 世界空间标注的常用做法：在精灵真正绘制前，根据相机距离
  // 将固定像素高度换算成世界尺寸，不依赖图谱组件是否转发帧回调。
  sprite.onBeforeRender = (renderer, scene, camera) => {
    if (!camera?.isPerspectiveCamera) return;
    const viewportHeight = Math.max(1, renderer.domElement.clientHeight);
    const distance = camera.position.distanceTo(sprite.getWorldPosition(worldPosition));
    const worldPerPixel = (2 * distance * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) / viewportHeight;
    const worldHeight = pixelHeight * worldPerPixel;
    sprite.scale.set(worldHeight * aspect, worldHeight, 1);
    sprite.updateMatrixWorld(true);
  };
  const initialWorldH = 3;
  const scale = initialWorldH / h;
  sprite.scale.set(w * scale, h * scale, 1);
  sprite.position.set(0, radius * 3.0 + 19, 0);
  return sprite;
}

export default StarfieldApp;
