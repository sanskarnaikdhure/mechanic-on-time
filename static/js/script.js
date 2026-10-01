document.addEventListener("DOMContentLoaded", function () {
    console.log("🔧 Mechanic on Time website loaded successfully.");

    initBookingFormDate();
    initSmoothScroll();
    initFormValidation();
    initNavbarActiveLink();
    initAutoDismissFlash();
    initPasswordMatch();
    initScrollAnimations();
    checkApiStatus();
});

function initBookingFormDate() {
    const dateInput = document.getElementById("date");
    if (!dateInput) return;

    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, "0");
    const dd = String(today.getDate()).padStart(2, "0");
    dateInput.min = `${yyyy}-${mm}-${dd}`;

    const timeInput = document.getElementById("time");
    if (timeInput) {
        timeInput.min = "08:00";
        timeInput.max = "21:00";
    }
}

function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener("click", function (e) {
            const href = this.getAttribute("href");
            if (!href || href === "#") return;

            const target = document.querySelector(href);
            if (target) {
                e.preventDefault();
                target.scrollIntoView({
                    behavior: "smooth",
                    block: "start"
                });
            }
        });
    });
}

function initFormValidation() {
    const bookingForm = document.querySelector('form[action="/booking"]');
    if (bookingForm) {
        bookingForm.addEventListener("submit", function (e) {
            const name = document.getElementById("name")?.value?.trim() || "";
            const phone = document.getElementById("phone")?.value?.trim() || "";
            const email = document.getElementById("email")?.value?.trim() || "";

            const errors = [];

            if (name.length < 2) errors.push("Please enter a valid name.");
            if (!/^[6-9]\d{9}$/.test(phone) && phone.length < 10) {
                errors.push("Please enter a valid phone number (10 digits).");
            }
            if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
                errors.push("Please enter a valid email address.");
            }

            if (errors.length > 0) {
                e.preventDefault();
                showInlineAlert(bookingForm, errors.join("\n"), "error");
            }
        });
    }

    const contactForm = document.querySelector('form[action="/contact"]');
    if (contactForm) {
        contactForm.addEventListener("submit", function (e) {
            const name = document.getElementById("name")?.value?.trim() || "";
            const email = document.getElementById("email")?.value?.trim() || "";
            const message = document.getElementById("message")?.value?.trim() || "";

            const errors = [];
            if (name.length < 2) errors.push("Please enter your name.");
            if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.push("Invalid email address.");
            if (message.length < 10) errors.push("Message should be at least 10 characters.");

            if (errors.length > 0) {
                e.preventDefault();
                showInlineAlert(contactForm, errors.join("\n"), "error");
            }
        });
    }
}

function initNavbarActiveLink() {
    const currentPath = window.location.pathname;
    document.querySelectorAll(".navbar nav a").forEach(link => {
        const href = link.getAttribute("href");
        if (!href) return;
        if (href === currentPath || (currentPath === "/" && href.startsWith("#"))) {
            if (!link.classList.contains("login-btn")) {
                link.style.color = "#f97316";
            }
        }
    });
}

function initAutoDismissFlash() {
    document.querySelectorAll('[style*="padding: 12px 16px"]').forEach(el => {
        if (el.textContent && (el.textContent.includes("success") ||
            el.textContent.includes("Thank") ||
            el.textContent.includes("Welcome") ||
            el.textContent.includes("logged") ||
            el.textContent.includes("Registration") ||
            el.textContent.includes("Please"))) {
            setTimeout(() => {
                el.style.transition = "opacity 0.5s ease";
                el.style.opacity = "0";
                setTimeout(() => el.remove(), 500);
            }, 5000);
        }
    });
}

function initPasswordMatch() {
    const password = document.getElementById("password");
    const confirm = document.getElementById("confirm_password");

    if (password && confirm) {
        const validate = () => {
            if (confirm.value && password.value !== confirm.value) {
                confirm.style.borderColor = "#ef4444";
                confirm.style.boxShadow = "0 0 0 3px rgba(239,68,68,0.10)";
            } else if (confirm.value) {
                confirm.style.borderColor = "#22c55e";
                confirm.style.boxShadow = "0 0 0 3px rgba(34,197,94,0.10)";
            } else {
                confirm.style.borderColor = "";
                confirm.style.boxShadow = "";
            }
        };
        password.addEventListener("input", validate);
        confirm.addEventListener("input", validate);
    }
}

function initScrollAnimations() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = "1";
                entry.target.style.transform = "translateY(0)";
            }
        });
    }, { threshold: 0.1 });

    document.querySelectorAll(".service-card, .why-card, .contact-card, .dashboard-card").forEach(el => {
        el.style.opacity = "0";
        el.style.transform = "translateY(20px)";
        el.style.transition = "opacity 0.6s ease, transform 0.6s ease";
        observer.observe(el);
    });
}

function showInlineAlert(form, message, type) {
    const existing = form.querySelector(".js-form-alert");
    if (existing) existing.remove();

    const alert = document.createElement("div");
    alert.className = "js-form-alert";
    alert.textContent = message;
    Object.assign(alert.style, {
        padding: "14px 18px",
        borderRadius: "8px",
        marginBottom: "20px",
        fontSize: "14px",
        lineHeight: "1.6",
        whiteSpace: "pre-line",
        background: type === "error" ? "#fee2e2" : "#dcfce7",
        color: type === "error" ? "#991b1b" : "#166534",
        borderLeft: `4px solid ${type === "error" ? "#ef4444" : "#22c55e"}`
    });

    form.insertBefore(alert, form.firstChild);

    setTimeout(() => {
        alert.style.transition = "opacity 0.4s";
        alert.style.opacity = "0";
        setTimeout(() => alert.remove(), 400);
    }, 6000);
}

function checkApiStatus() {
    if (window.location.pathname === "/" || window.location.pathname === "/dashboard") {
        fetch("/api/status")
            .then(r => r.json())
            .then(data => {
                console.log("📊 System Status:", data);
                if (data.mongodb_connected) {
                    console.log("✅ MongoDB connected:", data.database);
                } else {
                    console.warn("⚠️  MongoDB not connected - using in-memory storage");
                }
            })
            .catch(err => console.log("Status check skipped:", err));
    }
}
