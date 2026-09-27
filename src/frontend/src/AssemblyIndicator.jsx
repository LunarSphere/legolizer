import React, { useEffect, useState } from 'react';

const PHRASES = ['sorting by color', 'hunting for a 1×2', 'checking the studs line up', 'staggering the seams', 'counting plates', 'digging for one more 2×4', 'pressing the roof on', 'looking under the sofa for a 1×1', 'tidying the leftovers'];
const UNIT = 5;
const HEIGHT = 6;
const COS = Math.cos(Math.PI / 6);
const TRAVEL = 2.2;
const AXES = { x: [1, 0, 0], '-x': [-1, 0, 0], y: [0, 1, 0], '-y': [0, -1, 0], z: [0, 0, 1] };
const IN_TIME = 0.45;
const IN_STAGGER = 0.32;
const HOLD = 0.7;
const OUT_TIME = 0.4;
const OUT_STAGGER = 0.16;
const GAP = 0.2;

// [width (x), depth (y), x, y, z, enter-from axis, exit-to axis]; every sequence starts and ends empty.
const SEQUENCES = [
  { exit: 'reverse', bricks: [[2, 2, 0, 0, 0, 'z', 'z'], [2, 1, 0, 1, 1, 'x', 'x'], [1, 1, 1, 1, 2, 'z', 'z']] },
  { exit: 'forward', bricks: [[2, 1, 0, 1, 0, '-x', 'x'], [1, 1, 2, 1, 0, 'x', 'x'], [1, 1, 0, 1, 1, '-x', 'x'], [2, 1, 1, 1, 1, 'x', 'x']] },
  { exit: 'reverse', bricks: [[3, 2, 0, 0, 0, 'y', 'y'], [2, 2, 1, 0, 1, '-x', '-x'], [1, 2, 2, 0, 2, 'z', 'z']] },
  { exit: 'together', bricks: [[1, 1, 0, 1, 0, '-x', '-x'], [1, 1, 2, 1, 0, 'x', 'x'], [3, 1, 0, 1, 1, 'z', 'z'], [1, 1, 1, 1, 2, 'z', 'z']] },
  { exit: 'reverse', bricks: [[2, 1, 0, 0, 0, '-y', '-y'], [1, 2, 2, 0, 0, 'x', 'x'], [2, 1, 1, 2, 0, 'y', 'y'], [1, 2, 0, 1, 0, '-x', '-x'], [2, 2, 0.5, 0.5, 1, 'z', 'z']] },
  { exit: 'forward', bricks: [[2, 1, 0, 1, 0, 'x', '-x'], [1, 2, 1, 0, 1, '-y', 'y'], [2, 1, 0, 1, 2, '-x', 'x']] },
];

const project = (x, y, z) => [(x - y) * COS * UNIT, (x + y) * UNIT / 2 - z * HEIGHT];
const points = corners => corners.map(corner => project(...corner).map(n => n.toFixed(2)).join(',')).join(' ');
const offset = axis => {
  const [ax, ay, az] = AXES[axis].map(n => n * TRAVEL);
  const [dx, dy] = project(ax, ay, az);
  return [`${dx.toFixed(2)}px`, `${dy.toFixed(2)}px`];
};

function layout({ exit, bricks }) {
  const count = bricks.length;
  const outStart = (count - 1) * IN_STAGGER + IN_TIME + HOLD;
  const outOrder = index => exit === 'together' ? 0 : exit === 'forward' ? index : count - 1 - index;
  const shapes = bricks.map(([w, d, x, y, z, from, to], index) => {
    const [x1, y1, z1] = [x + w, y + d, z + 1];
    const [fx, fy] = offset(from);
    const [tx, ty] = offset(to);
    const studs = [];
    for (let i = 0; i < Math.round(w); i++) for (let j = 0; j < Math.round(d); j++) studs.push(project(x + i + 0.5, y + j + 0.5, z1));
    return {
      depth: z * 100 + x + w / 2 + y + d / 2,
      top: points([[x, y, z1], [x1, y, z1], [x1, y1, z1], [x, y1, z1]]),
      right: points([[x1, y, z1], [x1, y1, z1], [x1, y1, z], [x1, y, z]]),
      left: points([[x, y1, z1], [x1, y1, z1], [x1, y1, z], [x, y1, z]]),
      studs: studs.sort((a, b) => a[1] - b[1]),
      style: { '--fx': fx, '--fy': fy, '--tx': tx, '--ty': ty, '--in': `${index * IN_STAGGER}s`, '--out': `${outStart + outOrder(index) * OUT_STAGGER}s` },
    };
  });
  const lastOut = exit === 'together' ? 0 : (count - 1) * OUT_STAGGER;
  return { shapes: shapes.sort((a, b) => a.depth - b.depth), duration: outStart + lastOut + OUT_TIME + GAP };
}

const ASSEMBLIES = SEQUENCES.map(layout);
const randomIndex = (length, not) => {
  const pick = Math.floor(Math.random() * (length - 1));
  return pick >= not ? pick + 1 : pick;
};

function AssemblyBricks() {
  const [run, setRun] = useState(() => ({ count: 0, index: Math.floor(Math.random() * ASSEMBLIES.length) }));
  const assembly = ASSEMBLIES[run.index];
  useEffect(() => {
    const timer = setTimeout(() => setRun({ count: run.count + 1, index: randomIndex(ASSEMBLIES.length, run.index) }), assembly.duration * 1000);
    return () => clearTimeout(timer);
  }, [run, assembly]);
  return <svg className="assembly-bricks" viewBox="-14 -20 28 36">
    <g key={run.count}>{assembly.shapes.map((shape, i) => <g key={i} className="iso-brick" style={shape.style}>
      <polygon className="top" points={shape.top} />
      <polygon className="left" points={shape.left} />
      <polygon className="right" points={shape.right} />
      {shape.studs.map(([cx, cy], j) => <g key={j} className="stud">
        <ellipse cx={cx} cy={cy} rx="1.6" ry=".95" />
        <ellipse cx={cx} cy={cy - 1} rx="1.6" ry=".95" />
      </g>)}
    </g>)}</g>
  </svg>;
}

export default function AssemblyIndicator() {
  const [phrase, setPhrase] = useState(() => Math.floor(Math.random() * PHRASES.length));
  useEffect(() => {
    const timer = setInterval(() => setPhrase(n => (n + 1) % PHRASES.length), 2400);
    return () => clearInterval(timer);
  }, []);
  return <span className="assembly-indicator" aria-hidden="true">
    <AssemblyBricks />
    <span className="assembly-phrase"><span key={phrase}>{PHRASES[phrase]}…</span></span>
  </span>;
}
