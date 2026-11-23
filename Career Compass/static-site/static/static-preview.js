document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-static-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const notice = document.createElement("p");
      notice.className = "static-form-notice";
      notice.setAttribute("role", "status");
      notice.textContent =
        "This is a static preview. This action needs the Python backend.";
      form.append(notice);
    });
  });
});
