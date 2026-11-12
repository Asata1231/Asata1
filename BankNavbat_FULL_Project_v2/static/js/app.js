document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".flash").forEach((el) => {
    setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateY(-8px)"; }, 4200);
    setTimeout(() => el.remove(), 4700);
  });

  document.querySelectorAll('input[type="date"]').forEach((input) => {
    if (!input.min) input.min = new Date().toISOString().split("T")[0];
  });
});
