document.addEventListener("DOMContentLoaded", () => {
  const taskList = document.querySelector(".task-list[data-plan-date]");
  if (taskList) {
    const planDate = taskList.dataset.planDate;
    const checkForNewDay = async () => {
      try {
        const response = await fetch("/api/day", {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (response.redirected) {
          window.location.assign(response.url);
          return;
        }
        if (!response.ok) return;
        const currentDay = await response.json();
        if (currentDay.date !== planDate) window.location.reload();
      } catch {
        // A temporary network interruption is retried by the next scheduled check.
      }
    };
    window.setInterval(checkForNewDay, 60_000);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") checkForNewDay();
    });
  }

  const mentorForm = document.querySelector(".mentor-form");
  if (mentorForm) {
    const messageInput = mentorForm.querySelector("#message");
    const browserReplyInput = mentorForm.querySelector(
      'input[name="browser_ai_reply"]'
    );
    const submitButton = mentorForm.querySelector('button[type="submit"]');
    const browserStatus = document.getElementById("mentor-browser-status");
    const providerStatus = document.getElementById("mentor-provider-label");
    const providerBadge = document.getElementById("mentor-provider-badge");
    const metaAvailable =
      document.getElementById("mentor-provider-status").dataset.metaAvailable ===
      "true";
    const fallbackStatus = metaAvailable
      ? "Browser AI is unavailable; the server will try Meta AI."
      : "Browser AI is unavailable; using private local career guidance.";
    const fallbackProvider = metaAvailable
      ? "Meta AI is the server fallback."
      : "Private local career guidance.";
    const fallbackBadge = metaAvailable ? "META AI FALLBACK" : "LOCAL GUIDE";
    let browserModel = null;
    let browserAvailability = "unavailable";
    let browserSession = null;

    try {
      browserModel = window.LanguageModel;
    } catch {
      browserModel = null;
    }

    const setFallbackStatus = () => {
      browserStatus.textContent = fallbackStatus;
      providerStatus.textContent = fallbackProvider;
      providerBadge.textContent = fallbackBadge;
    };
    const submitToServer = () => {
      browserAvailability = "unavailable";
      setFallbackStatus();
      HTMLFormElement.prototype.submit.call(mentorForm);
    };

    if (
      !browserModel ||
      typeof browserModel.availability !== "function" ||
      typeof browserModel.create !== "function"
    ) {
      setFallbackStatus();
    } else {
      browserModel
        .availability()
        .then((availability) => {
          browserAvailability = availability;
          if (availability === "available") {
            browserStatus.textContent =
              "On-device browser AI is ready. Your question stays on this device.";
            providerStatus.textContent = "On-device AI is ready.";
            providerBadge.textContent = "ON-DEVICE AI";
          } else if (
            availability === "downloadable" ||
            availability === "downloading"
          ) {
            browserStatus.textContent =
              "On-device browser AI can be prepared when you send a message. The first use may download a model.";
            providerStatus.textContent = "On-device AI is available.";
            providerBadge.textContent = "ON-DEVICE AI";
          } else {
            setFallbackStatus();
          }
        })
        .catch(setFallbackStatus);

      mentorForm.addEventListener("submit", (event) => {
        if (
          !["available", "downloadable", "downloading"].includes(
            browserAvailability
          )
        ) {
          return;
        }

        event.preventDefault();
        submitButton.disabled = true;
        browserStatus.textContent =
          browserAvailability === "available"
            ? "Thinking with on-device AI…"
            : "Preparing the on-device model. Its first download may take a little while…";

        let context = {};
        try {
          context = JSON.parse(
            document.getElementById("mentor-browser-context").textContent
          );
        } catch {
          submitToServer();
          return;
        }

        const careerDescription = context.career
          ? `Selected career: ${context.career}${
              context.career_category ? ` (${context.career_category})` : ""
            }.`
          : "The user has not selected a career yet.";
        const taskDescription = context.task
          ? `Current task: ${context.task.title}. Goal: ${
              context.task.deliverable
            }. Steps: ${(context.task.steps || []).join(" ")}.`
          : "";
        const systemPrompt = [
          "You are a thoughtful, practical career mentor. Answer the user's actual question, including hypotheticals. State assumptions, explain trade-offs, and give specific, manageable next steps.",
          careerDescription,
          `The user's selected market region is ${context.market_region || "unspecified"}.`,
          taskDescription,
          "Do not invent current salary, hiring, licensing, or labor-market statistics. If current evidence is needed, say that it should be checked against the Career Compass career outlook sources.",
          "Do not claim to be a licensed professional or give medical, legal, or financial advice. Be encouraging, concise, and clear about uncertainty.",
        ]
          .filter(Boolean)
          .join("\n");
        const initialPrompts = [
          { role: "system", content: systemPrompt },
          ...(Array.isArray(context.history) ? context.history.slice(-8) : []),
        ];
        let createSession;
        try {
          createSession = browserSession
            ? Promise.resolve(browserSession)
            : browserModel.create({
                initialPrompts,
                monitor(monitor) {
                  monitor.addEventListener("downloadprogress", (progress) => {
                    browserStatus.textContent = `Preparing on-device AI: ${Math.round(
                      progress.loaded * 100
                    )}% downloaded…`;
                  });
                },
              });
        } catch {
          submitToServer();
          return;
        }

        createSession
          .then(async (session) => {
            browserSession = session;
            const reply = (await session.prompt(messageInput.value.trim())).trim();
            if (!reply) throw new Error("The browser model returned an empty reply.");
            browserReplyInput.value = reply.slice(0, 4000);
            browserStatus.textContent = "Reply ready. Saving your conversation…";
            HTMLFormElement.prototype.submit.call(mentorForm);
          })
          .catch(() => {
            submitToServer();
          });
      });
    }
  }

  const form = document.querySelector(".assessment-form");
  if (!form) return;

  const questions = [...form.querySelectorAll(".question")];
  const count = document.getElementById("answered-count");
  const bar = document.getElementById("assessment-progress-bar");
  const requirement = document.getElementById("answer-requirement");
  const minimumAnswers = Number(
    document.querySelector(".assessment-progress").dataset.minimumAnswers
  );
  const updateProgress = () => {
    const answered = questions.filter((question) =>
      question.querySelector('input[type="radio"]:checked')
    ).length;
    count.textContent = answered;
    bar.style.width = `${Math.round((answered / questions.length) * 100)}%`;
    requirement.textContent =
      answered >= minimumAnswers
        ? "Enough to get your estimate"
        : `${minimumAnswers - answered} more needed`;
  };
  form.addEventListener("change", updateProgress);
  updateProgress();
});
