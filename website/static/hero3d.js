/* Hero 3D scene: floating exam papers + brand geometry, slow drift with mouse
   parallax. Kept deliberately light - a handful of meshes, no textures, no
   post-processing - so it runs smoothly on school laptops and phones. */

import * as THREE from "./vendor/three.module.js";

const canvas = document.getElementById("hero-canvas");
if (canvas) {
  const NAVY = 0x293554, GOLD = 0xf4a632, WHITE = 0xffffff;

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true,
                                             antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  cam.position.set(0, 0, 11);

  scene.add(new THREE.AmbientLight(WHITE, 1.15));
  const sun = new THREE.DirectionalLight(WHITE, 1.4);
  sun.position.set(4, 6, 8);
  scene.add(sun);

  const group = new THREE.Group();
  scene.add(group);

  // Floating "exam papers": thin white boxes with a navy edge
  const paperGeo = new THREE.BoxGeometry(2.6, 3.6, 0.045);
  const paperMat = new THREE.MeshStandardMaterial({ color: WHITE,
    roughness: 0.85 });
  const papers = [];
  const layout = [
    { x: -0.6, y:  0.3, z:  0.0, rz: -0.10, ry:  0.28 },
    { x:  1.4, y: -0.7, z: -1.2, rz:  0.14, ry: -0.20 },
    { x: -2.1, y: -1.4, z: -2.2, rz:  0.06, ry:  0.45 },
  ];
  for (const p of layout) {
    const m = new THREE.Mesh(paperGeo, paperMat);
    m.position.set(p.x, p.y, p.z);
    m.rotation.set(0, p.ry, p.rz);
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(paperGeo),
      new THREE.LineBasicMaterial({ color: NAVY, transparent: true,
                                    opacity: 0.35 }));
    m.add(edges);
    // "text lines" on the paper: flat navy strips
    for (let i = 0; i < 6; i++) {
      const line = new THREE.Mesh(
        new THREE.BoxGeometry(1.8 - (i % 3) * 0.35, 0.08, 0.01),
        new THREE.MeshBasicMaterial({ color: NAVY, transparent: true,
                                      opacity: 0.18 }));
      line.position.set(-0.15 + (i % 3) * 0.08, 1.25 - i * 0.42, 0.03);
      m.add(line);
    }
    group.add(m);
    papers.push({ mesh: m, phase: Math.random() * Math.PI * 2 });
  }

  // Brand geometry: gold wireframe icosahedron + solid navy torus
  const ico = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1.05, 0),
    new THREE.MeshStandardMaterial({ color: GOLD, wireframe: true }));
  ico.position.set(2.6, 1.6, -0.6);
  group.add(ico);

  const torus = new THREE.Mesh(
    new THREE.TorusGeometry(0.55, 0.2, 20, 48),
    new THREE.MeshStandardMaterial({ color: NAVY, roughness: 0.4,
                                     metalness: 0.15 }));
  torus.position.set(-2.6, 1.7, -1.0);
  group.add(torus);

  const dot = new THREE.Mesh(
    new THREE.SphereGeometry(0.28, 24, 24),
    new THREE.MeshStandardMaterial({ color: GOLD, roughness: 0.35 }));
  dot.position.set(2.3, -1.9, 0.4);
  group.add(dot);

  // Mouse parallax (eased)
  let tx = 0, ty = 0, px = 0, py = 0;
  addEventListener("pointermove", (e) => {
    tx = (e.clientX / innerWidth - 0.5) * 0.5;
    ty = (e.clientY / innerHeight - 0.5) * 0.35;
  });

  function size() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== w || canvas.height !== h) {
      renderer.setSize(w, h, false);
      cam.aspect = w / h;
      cam.updateProjectionMatrix();
    }
  }

  renderer.setAnimationLoop((t) => {
    size();
    const s = t / 1000;
    for (const { mesh, phase } of papers) {
      mesh.position.y += Math.sin(s * 0.8 + phase) * 0.0016;
      mesh.rotation.z += Math.sin(s * 0.5 + phase) * 0.0004;
    }
    ico.rotation.x = s * 0.25;
    ico.rotation.y = s * 0.35;
    torus.rotation.x = s * 0.4;
    torus.rotation.y = s * 0.2;
    px += (tx - px) * 0.05;
    py += (ty - py) * 0.05;
    group.rotation.y = px;
    group.rotation.x = py;
    renderer.render(scene, cam);
  });
}
