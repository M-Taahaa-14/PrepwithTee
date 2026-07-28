(function () {
  /* PrepWithTee doubt solver — photo of a question in, worked solution out. */
  const $ = (s) => document.querySelector(s);

  const drop = $("#drop");
const fileInput = $("#file");
const go = $("#go");
let dataUrl = null;

function status(msg, cls = "") {
  const el = $("#status");
  el.textContent = msg;
  el.className = "status " + cls;
}

/* Phone cameras produce 4-6 MB shots; downscaling in the browser keeps the
   upload quick and stays well under the request limit without the student
   having to think about it. */
function shrink(file, maxEdge = 1600) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read that file."));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("That file is not a readable image."));
      img.onload = () => {
        const scale = Math.min(1, maxEdge / Math.max(img.width, img.height));
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * scale);
        c.height = Math.round(img.height * scale);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        resolve(c.toDataURL("image/jpeg", 0.85));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

async function accept(file) {
  if (!file || !file.type.startsWith("image/")) {
    return status("Pick an image file — PNG, JPG or WebP.", "err");
  }
  status("Preparing your photo…");
  try {
    dataUrl = await shrink(file);
  } catch (err) {
    return status(err.message, "err");
  }
  drop.innerHTML = `<img src="${dataUrl}" alt="Your question">
    <small style="display:block;margin-top:10px">Tap to choose a different photo</small>`;
  drop.appendChild(fileInput);
  go.disabled = false;
  status("");
}

fileInput.onchange = (e) => accept(e.target.files[0]);

drop.addEventListener("dragover", (e) => {
  e.preventDefault();
  drop.classList.add("over");
});
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  accept(e.dataTransfer.files[0]);
});

// Let students paste a screenshot straight in — faster than saving it first.
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])]
    .find((i) => i.type.startsWith("image/"));
  if (item) accept(item.getAsFile());
});

go.onclick = async () => {
  if (!dataUrl) return;
  go.disabled = true;
  go.innerHTML = '<span class="spinner"></span>Working it out…';
  status("");
  try {
    const r = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: dataUrl, note: $("#note").value || null }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || `Something went wrong (${r.status}).`);
    $("#out").innerHTML = body.html;
    $("#out").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    status(err.message, "err");
  } finally {
    go.disabled = false;
    go.textContent = "Work it out";
  }
};
})();
