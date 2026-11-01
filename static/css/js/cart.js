// cart.js — v2 with event delegation (works no matter when buttons render)

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  let data = {};
  try { data = await res.json(); } catch (e) {}
  return { status: res.status, data };
}

function updateCartCount(n) {
  const el = document.getElementById("cart-count");
  if (el && typeof n === "number") el.textContent = n;
}

async function refreshCount() {
  try {
    const res = await fetch("/api/cart/count", { credentials: "same-origin" });
    const data = await res.json();
    updateCartCount(data.count);
  } catch (e) { console.error("count fetch failed", e); }
}

function goToLogin() {
  const next = encodeURIComponent(window.location.pathname);
  window.location.href = "/login?next=" + next;
}

document.addEventListener("click", async (e) => {
  const addBtn = e.target.closest(".add-btn");
  if (addBtn) {
    e.preventDefault();
    const id = addBtn.dataset.id;
    if (!id) { console.error("add-btn has no data-id"); return; }
    try {
      const { status, data } = await postJSON("/api/cart/add", { id });
      if (status === 401) { goToLogin(); return; }
      if (data.success) {
        updateCartCount(data.cart_count);
        const original = addBtn.textContent;
        addBtn.textContent = "Added ✓";
        addBtn.disabled = true;
        setTimeout(() => {
          addBtn.textContent = original;
          addBtn.disabled = false;
        }, 700);
      } else {
        alert(data.error || "Could not add to cart");
      }
    } catch (err) {
      console.error(err);
      alert("Network error. Check the Flask terminal.");
    }
    return;
  }

  const removeBtn = e.target.closest(".remove-btn");
  if (removeBtn) {
    e.preventDefault();
    const id = removeBtn.dataset.id;
    const { status, data } = await postJSON("/api/cart/remove", { id });
    if (status === 401) { goToLogin(); return; }
    if (data.success) {
      updateCartCount(data.cart_count);
      location.reload();
    }
  }
});

document.addEventListener("DOMContentLoaded", refreshCount);