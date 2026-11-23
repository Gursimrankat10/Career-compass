import random

from careers import tasks_for_career


_COMMON_QUESTIONS = [
    {
        "dimension": "analytical",
        "level": 1,
        "prompt": "A pilot program reports a 24% improvement, but participants volunteered and there was no comparison group. Which conclusion is best supported?",
        "options": [
            "The pilot is promising, but selection effects and the missing comparison prevent attributing the change to the program.",
            "The program caused a 24% improvement because participants completed it.",
            "The result proves the program will work equally well in the wider population.",
            "The percentage is unusable unless the pilot had thousands of participants.",
        ],
        "answer": 0,
        "explanation": "A before-and-after result without a comparison group cannot separate the program's effect from selection, time, or other changes.",
    },
    {
        "dimension": "analytical",
        "level": 1,
        "prompt": "A screening tool is used where only 1 in 500 cases has the condition. It catches most true cases, but produces many false positives. What should be checked before interpreting a positive result?",
        "options": [
            "The positive predictive value at this prevalence and the consequences of follow-up testing.",
            "Only the tool's sensitivity, because high sensitivity makes a positive result conclusive.",
            "Only its overall accuracy, without separating false positives from false negatives.",
            "Whether the positive score is higher than the average score in the study.",
        ],
        "answer": 0,
        "explanation": "When the condition is rare, even a sensitive tool can produce many false positives; predictive value depends on prevalence and error costs.",
    },
    {
        "dimension": "detail",
        "level": 1,
        "prompt": "Two reports give different national employment figures. One counts people employed at any point in a year; the other counts people employed in a survey week. What is the first sound comparison step?",
        "options": [
            "Align the population, reference period, definitions, and collection methods before comparing the numbers.",
            "Average the two figures to reduce measurement noise.",
            "Prefer the larger sample without checking what each sample represents.",
            "Treat the difference as a trend because the reports use different methods.",
        ],
        "answer": 0,
        "explanation": "Different definitions and reference periods measure different quantities; they must be reconciled before the values can be compared.",
    },
    {
        "dimension": "analytical",
        "level": 1,
        "prompt": "A training course has a high completion rate, but learners were allowed to stop reporting their outcomes at any time. Which follow-up best addresses the main uncertainty?",
        "options": [
            "Report who is missing and compare follow-up rates and outcomes across relevant groups.",
            "Treat completers as representative because they finished the course.",
            "Count every person lost to follow-up as a successful placement.",
            "Use the completion rate as a substitute for employment outcomes.",
        ],
        "answer": 0,
        "explanation": "Missing outcomes can be systematic; examining attrition and subgroup follow-up helps assess whether the reported result is biased.",
    },
    {
        "dimension": "detail",
        "level": 1,
        "prompt": "A chart shows a sharp rise after its vertical axis is truncated. What should you inspect before repeating its headline?",
        "options": [
            "The full axis scale, absolute values, time window, and denominator.",
            "The colors and labels, since clear styling confirms the scale.",
            "Only the percentage change, because percentages remove scale effects.",
            "Whether the plotted line has enough points to look smooth.",
        ],
        "answer": 0,
        "explanation": "Axis range, denominator, and time window determine what a visual change means; a cropped axis can exaggerate its apparent size.",
    },
    {
        "dimension": "people",
        "level": 1,
        "prompt": "A group-wide result improves, while one subgroup's result falls. What is the most responsible next analysis?",
        "options": [
            "Check subgroup sample sizes, uncertainty, baseline differences, and whether the intervention worked differently.",
            "Use the group average because it is based on more observations.",
            "Conclude the subgroup is an outlier and exclude it from the report.",
            "Assume the subgroup difference is causal because it moved in the opposite direction.",
        ],
        "answer": 0,
        "explanation": "Aggregate results can mask uneven effects; subgroup estimates need uncertainty and baseline context before drawing conclusions.",
    },
    {
        "dimension": "analytical",
        "level": 1,
        "prompt": "A small experiment tests 20 outcomes and highlights the one with p < .05. What should strengthen the claim?",
        "options": [
            "A pre-specified primary outcome or an appropriate multiple-comparison correction, followed by replication.",
            "A larger effect estimate selected from the 20 outcomes.",
            "A post-hoc explanation for why the highlighted outcome was expected.",
            "Reporting only the significant result so readers are not distracted.",
        ],
        "answer": 0,
        "explanation": "Trying many outcomes increases false-positive risk; pre-specification, correction, and independent replication make the evidence more credible.",
    },
    {
        "dimension": "organization",
        "level": 1,
        "prompt": "A project has a fixed budget and two proposals: one offers a large uncertain benefit, the other a smaller reliable benefit. What makes the decision auditable?",
        "options": [
            "Compare expected benefit, uncertainty, downside, and reversibility against an agreed objective.",
            "Choose the proposal with the largest best-case benefit.",
            "Choose the proposal with the narrowest estimate, regardless of impact.",
            "Avoid recording assumptions so the team can adapt later.",
        ],
        "answer": 0,
        "explanation": "A decision record that makes the objective, assumptions, uncertainty, and downside visible supports reasoned trade-offs.",
    },
    {
        "dimension": "detail",
        "level": 1,
        "prompt": "A public dataset changes its definition halfway through the series. What is the most defensible trend analysis?",
        "options": [
            "Locate the series break, document the definition change, and compare only compatible periods or use an official bridge.",
            "Connect every point because the field name is unchanged.",
            "Rescale the post-change values until the line looks continuous.",
            "Drop the date labels and compare the overall direction.",
        ],
        "answer": 0,
        "explanation": "A changed measurement definition creates a break in comparability; the break must be handled transparently, not smoothed away.",
    },
    {
        "dimension": "people",
        "level": 1,
        "prompt": "A policy is evaluated using records from people who could access the service. Which limitation should be stated?",
        "options": [
            "The findings may not transfer to people excluded by access, eligibility, or missing records.",
            "The findings apply to everyone because the records are real-world data.",
            "The limitation disappears if the dataset contains many records.",
            "The evaluation is invalid unless it uses a randomized trial.",
        ],
        "answer": 0,
        "explanation": "Large datasets can still omit systematically excluded populations; sample size does not establish representativeness.",
    },
    {
        "dimension": "detail",
        "level": 2,
        "prompt": "A survey weights respondents to match the population on age and region. Non-response is still related to income within those groups. What follows?",
        "options": [
            "The weighting may not remove non-response bias; compare response patterns and test sensitivity to plausible missing outcomes.",
            "Matching age and region guarantees an unbiased estimate.",
            "The estimate is unbiased if the weighted sample size is large.",
            "The income relationship should be ignored because it was not a weighting variable.",
        ],
        "answer": 0,
        "explanation": "Weighting corrects only the imbalances it models; outcome-related non-response within weighting cells can remain a source of bias.",
    },
    {
        "dimension": "analytical",
        "level": 2,
        "prompt": "A team repeatedly checks a dashboard and stops a trial as soon as the result becomes significant. Which change best reduces false-positive risk?",
        "options": [
            "Use a pre-specified sample size or a sequential-testing method with valid stopping boundaries.",
            "Keep the same p-value threshold but check the dashboard less carefully.",
            "Run more variants and retain only the strongest result.",
            "Stop whenever the confidence interval first excludes zero.",
        ],
        "answer": 0,
        "explanation": "Repeated unadjusted significance checks inflate false-positive risk; planned stopping rules or valid sequential methods address it.",
    },
    {
        "dimension": "analytical",
        "level": 2,
        "prompt": "A model performs well on a random train/test split, but many records from the same person appear in both sets. What is the key risk?",
        "options": [
            "Identity-specific information can leak across the split; evaluate with person-level or time-appropriate separation.",
            "The model is necessarily underfit because both sets have similar records.",
            "The random split proves the model will generalize to new people.",
            "Only class balance matters once the test set is large enough.",
        ],
        "answer": 0,
        "explanation": "Related records across splits leak information and make test performance optimistic; the split must reflect the intended deployment population.",
    },
    {
        "dimension": "detail",
        "level": 2,
        "prompt": "A source reports a wage median but combines full-time and part-time workers and omits the survey year. What can you safely claim?",
        "options": [
            "Very little about current full-time pay; find the year, population, geography, and wage definition before using it.",
            "It is a current full-time salary estimate because medians resist outliers.",
            "It is suitable for all regions if the currency is converted.",
            "It is comparable to annual salary after multiplying by standard work hours.",
        ],
        "answer": 0,
        "explanation": "A median does not resolve a mismatched population, period, geography, or pay definition; those metadata are essential.",
    },
    {
        "dimension": "analytical",
        "level": 2,
        "prompt": "Two interventions are compared on average outcomes, but one serves higher-risk participants. Which analysis is most informative?",
        "options": [
            "Compare baseline risk and assignment mechanisms, then use an appropriate adjusted estimate with uncertainty and sensitivity checks.",
            "Rank interventions by the unadjusted mean and ignore participant mix.",
            "Subtract the average baseline score from each outcome without checking the design.",
            "Select the intervention with the better result in the largest subgroup.",
        ],
        "answer": 0,
        "explanation": "Different baseline risk and selection can confound raw averages; adjustment must respect the study design and be accompanied by uncertainty checks.",
    },
    {
        "dimension": "people",
        "level": 2,
        "prompt": "A recommender improves average engagement but repeatedly gives one demographic group fewer useful options. What is the best next step?",
        "options": [
            "Measure group-specific error and utility, investigate data and product mechanisms, and test mitigations with affected users.",
            "Keep the system because the average metric improved.",
            "Remove demographic fields and assume disparate outcomes will disappear.",
            "Lower every group's recommendation threshold equally.",
        ],
        "answer": 0,
        "explanation": "Average engagement can conceal unequal harm; evaluate relevant group outcomes and test the mechanism rather than assume a single fix.",
    },
    {
        "dimension": "analytical",
        "level": 2,
        "prompt": "A service launch and an outcome both vary by region. The service launched first where outcomes were already improving. Which evidence would best help separate the launch effect from the pre-existing trend?",
        "options": [
            "Comparable pre-launch trends and a defensible comparison group, with a design that accounts for rollout timing.",
            "A large post-launch sample from the launch regions only.",
            "A before/after chart with no comparison because the launch date is known.",
            "A survey asking launch-region users whether the service helped.",
        ],
        "answer": 0,
        "explanation": "A credible counterfactual requires comparison and trend assumptions; a coincident before/after change alone does not establish attribution.",
    },
    {
        "dimension": "detail",
        "level": 2,
        "prompt": "A model's overall error rate is low, but its errors are concentrated on a small, high-consequence subgroup. How should a deployment decision be made?",
        "options": [
            "Report subgroup uncertainty and harm, set use-specific thresholds or safeguards, and defer deployment if residual risk is unacceptable.",
            "Deploy because the overall error rate is the most stable metric.",
            "Combine the subgroup with a larger group to improve statistical power.",
            "Increase the training set without measuring post-change subgroup performance.",
        ],
        "answer": 0,
        "explanation": "Aggregate accuracy does not bound subgroup harm; decisions should reflect use-specific consequences and validated subgroup performance.",
    },
]


_CAREER_TRACKS = {
    "technology": {
        "software-developer", "cybersecurity-analyst", "cloud-engineer",
    },
    "data": {"data-analyst", "sports-analyst", "machine-learning-engineer"},
    "design": {"ux-designer", "graphic-designer", "game-designer"},
    "health": {
        "healthcare", "psychologist", "nurse", "physical-therapist",
        "sports-physiotherapist",
    },
    "sports": {
        "football-player", "basketball-player", "cricketer", "athletics-coach",
    },
    "business": {
        "entrepreneur", "product-manager", "project-manager", "sales-consultant",
        "digital-marketer", "human-resources-specialist",
    },
    "finance": {"financial-analyst", "accountant"},
    "engineering": {"civil-engineer", "mechanical-engineer", "electrician"},
    "science": {
        "environmental-scientist", "research-scientist", "agricultural-scientist",
    },
    "education": {"teacher"},
    "public_service": {"lawyer", "policy-analyst", "social-worker"},
    "media": {"writer-editor"},
    "hospitality": {"chef"},
}


_DOMAIN_QUESTION_BANK = {
    "technology": [
        ("analytical", 1, "An API retry can arrive after the first request succeeded but before its response reached the caller. Which design best prevents a duplicate payment?", ["Require an idempotency key and persist the original outcome for retries.", "Retry only when the caller uses a new request ID.", "Return success before writing the payment record.", "Deduplicate requests by matching amount and timestamp."], 0, "A stable idempotency key lets the service return the original result without repeating a non-idempotent side effect."),
        ("detail", 2, "A server-side request forgery report shows a URL parser accepts an allowed hostname, but the resolved address is private. Which defense addresses the critical gap?", ["Validate the resolved IP on every redirect and connection, and block private, loopback, and link-local ranges.", "Check that the original URL begins with the allowed hostname string.", "Block only HTTP and permit HTTPS to the same destination.", "Validate the DNS result once and trust redirects."], 0, "Hostname-string checks do not constrain DNS resolution or redirects; validate the actual destination addresses at connection time."),
        ("analytical", 3, "A service's p95 latency rises after a release while mean latency is flat. Which investigation best distinguishes a broad slowdown from a small tail regression?", ["Compare latency distributions by endpoint and cohort, trace slow requests, and check queueing and outlier dependencies.", "Roll back based on the mean because it is stable.", "Increase all request timeouts so fewer calls fail.", "Compare only total request volume before and after the release."], 0, "Tail latency can worsen for a subset while the mean stays flat; segmented distributions and traces identify where the tail changed."),
    ],
    "data": [
        ("analytical", 1, "A classifier scores 0.94 AUC on a random split, but deployment predicts next month's cases for unseen clients. Which validation is most defensible?", ["Split by client and time so future records and unseen clients cannot leak into training.", "Tune the classification threshold on the test labels and report the resulting AUC.", "Oversample the test set until its class balance matches training.", "Randomly split individual rows again with a larger test set."], 0, "Evaluation must mirror the intended future, unseen-client setting; row-level random splitting can leak client identity and future information."),
        ("detail", 2, "A regional conversion rate falls after a campaign, while the overall rate rises. What is the first explanation to test?", ["Whether traffic mix shifted toward regions with different baseline rates, producing an aggregate reversal.", "Whether the overall rate is necessarily wrong because a subgroup declined.", "Whether the lower regional rate should be excluded as noise.", "Whether averaging regional percentages will remove the reversal."], 0, "A changing mix of groups with different baseline rates can reverse an aggregate trend; compare denominators and standardized rates."),
        ("analytical", 3, "A feature experiment has a positive overall effect, but treatment allocation was uneven across a major seasonal boundary. Which analysis is strongest?", ["Check randomization and exposure by time, estimate with pre-specified time strata or a justified model, and report sensitivity.", "Remove all observations after the boundary to preserve the positive estimate.", "Control for every post-treatment variable to make the groups equivalent.", "Report the raw mean difference because randomization prevents any imbalance."], 0, "Randomization does not guarantee balance in every finite sample; time-aware analysis and sensitivity checks expose whether seasonality drives the estimate."),
    ],
    "design": [
        ("people", 1, "A redesign raises completed checkouts, but the experiment also removes a required accessibility step for keyboard users. What is the sound decision?", ["Treat conversion and access as separate outcomes; investigate the accessibility regression before shipping.", "Ship because the primary conversion metric improved.", "Keep the redesign and add a keyboard note to the release summary.", "Compare only users who completed checkout."], 0, "An average conversion gain does not offset an accessibility barrier; assess the affected task and fix the regression before release."),
        ("analytical", 2, "In a usability test, participants complete a task faster after a new layout, but they make more consequential errors. Which evaluation best captures the trade-off?", ["Compare completion, error severity, recovery, and comprehension, then test revisions against the target task.", "Use completion time because it is objective.", "Average time and error count into one score without weighting consequences.", "Discard the test because speed and errors disagree."], 0, "Usability is not a single speed metric; error impact, recovery, and task success need to be evaluated together."),
        ("creative", 3, "An interface test favors one variant, but participants saw it after a different tutorial and the prototype order was not randomized. What should happen before claiming a design effect?", ["Repeat with counterbalanced exposure or equivalent instructions and a measure tied to the target behavior.", "Use the variant with more positive comments.", "Treat the tutorial difference as part of the design effect.", "Increase the number of questions asked after each variant."], 0, "Tutorial and order effects are alternative explanations; control exposure and use comparable, outcome-focused measures."),
    ],
    "health": [
        ("practical", 1, "A patient reports new severe symptoms that are outside your role's training and the scheduled appointment is soon. What is the appropriate response?", ["Follow the service's urgent escalation protocol and involve a qualified clinician; do not independently diagnose.", "Wait for the appointment because the patient already has a booking.", "Search for a likely diagnosis and recommend treatment to save time.", "Document the symptoms but avoid notifying anyone until the next shift."], 0, "New severe symptoms require timely escalation within role boundaries, not an unqualified diagnosis or delay."),
        ("detail", 2, "A care intervention appears effective in a small uncontrolled case series, but patients were selected after responding well. Which limitation matters most?", ["Selection on response and the lack of a comparison make the effect difficult to attribute or generalize.", "The sample is too small to report any observations at all.", "The intervention is proven because outcomes followed treatment.", "The results apply only if every participant received the same dose."], 0, "Selecting observed responders and lacking a comparison group creates strong selection and attribution limits."),
        ("analytical", 3, "A screening result is positive, the condition is rare, and a confirmatory test is available. What should guide the next step?", ["Use the validated confirmatory pathway and interpret the screening result with prevalence and clinical context.", "Treat the positive screen as a definitive diagnosis.", "Repeat the same screen until it becomes negative.", "Ignore the screen because rare conditions have low predictive value."], 0, "Screening changes probability, not certainty; follow validated confirmation and interpretation pathways with qualified professionals."),
    ],
    "sports": [
        ("practical", 1, "An athlete's performance drops after consecutive high-load sessions, while soreness and sleep disruption rise. Which coaching response is best supported?", ["Reduce or modify load, assess recovery and symptoms, and follow qualified medical guidance for concerning signs.", "Increase intensity to overcome the performance dip.", "Keep the plan unchanged because one poor session is normal.", "Use soreness alone to diagnose an injury."], 0, "A cluster of performance and recovery signals warrants a load adjustment and appropriate medical escalation, not diagnosis from one measure."),
        ("analytical", 2, "A player has the highest scoring average but also the highest turnover rate and plays against weaker opponents more often. Which comparison is fairest?", ["Compare role-adjusted performance with possession, opponent strength, minutes, and uncertainty.", "Rank players by scoring average because points are the goal.", "Compare raw totals after removing games with low scores.", "Use the latest game because it reflects current form."], 0, "Role, exposure, opposition, and uncertainty affect raw averages; a fair comparison accounts for these factors."),
        ("detail", 3, "A training block improves a jump metric, but the test protocol and equipment changed halfway through. What conclusion is warranted?", ["The series may not be comparable; establish measurement equivalence before attributing the change to training.", "The improvement is causal because the training block came first.", "Average the two protocols to create one baseline.", "Discard the earlier tests and use the highest result."], 0, "A changed protocol can create an artificial shift; verify measurement comparability before interpreting the trend."),
    ],
    "business": [
        ("analytical", 1, "A product change increases sign-ups, but most new users leave before completing the core task and support contacts rise. What is the best success assessment?", ["Evaluate activation, task success, retention, support burden, and acquisition quality against the product goal.", "Declare success because the sign-up funnel improved.", "Undo the change because support contacts rose.", "Optimize sign-ups further and evaluate retention later."], 0, "A funnel entry metric can improve while user value falls; assess downstream outcomes and costs."),
        ("organization", 2, "A project is late because a shared specialist is overallocated across three teams. Which plan most directly addresses the constraint?", ["Make the bottleneck and dependencies visible, then re-sequence work or negotiate capacity and scope.", "Add more parallel tasks so teams have something to do.", "Ask each team to keep its original deadline privately.", "Track individual effort more closely without changing the queue."], 0, "The shared specialist is the system constraint; capacity, sequencing, and scope decisions are more effective than local activity tracking."),
        ("analytical", 3, "A sales team attributes revenue growth to a new script, but the team also received better leads and a seasonal demand spike. What evidence best tests the attribution?", ["Use a randomized or credible matched comparison with lead quality and timing measured before the intervention.", "Compare total revenue with the previous month.", "Ask top performers whether the script felt effective.", "Compare only the deals that closed after using the script."], 0, "Lead mix and seasonality confound a simple before/after comparison; a credible counterfactual is needed."),
    ],
    "finance": [
        ("analytical", 1, "A firm reports rising profit while operating cash flow falls because receivables and inventory grow. Which interpretation is most careful?", ["Investigate working-capital conversion and earnings quality; profit and cash flow reflect different timing.", "Conclude the profit is fraudulent because cash flow fell.", "Ignore receivables because revenue is already recognized.", "Compare profit only with the prior period's cash balance."], 0, "Accrual profit and operating cash flow differ in timing; working-capital movements can explain divergence but need investigation."),
        ("detail", 2, "A forecast shows a single expected return but depends heavily on one uncertain growth assumption. What improves decision usefulness?", ["Show scenario and sensitivity ranges, expose the assumption, and distinguish nominal from real and pre- from post-tax values.", "Add decimal places to the expected return.", "Use the most optimistic assumption because forecasts are uncertain.", "Replace the model with the historical average."], 0, "Sensitivity and scenario analysis show how fragile a point estimate is and clarify the basis of comparison."),
        ("analytical", 3, "A portfolio's return exceeds a benchmark, but it took materially greater risk and held different sector exposures. Which comparison is most informative?", ["Examine risk-adjusted and factor/sector exposures over the same period, including fees and uncertainty.", "Compare nominal returns because all investors seek growth.", "Choose a shorter interval that highlights the outperformance.", "Subtract the benchmark return from each holding's price."], 0, "Raw return omits risk, exposure, horizon, and fees; fair performance analysis accounts for them."),
    ],
    "engineering": [
        ("practical", 1, "A structure passes a simplified static-load calculation, but cyclic loading and fatigue are plausible. What should the design review do?", ["Assess relevant fatigue and dynamic failure modes using applicable standards and qualified engineering review.", "Accept the design because the static safety factor is adequate.", "Increase material thickness without evaluating the failure mode.", "Use the largest observed load as the only design case."], 0, "Static capacity does not establish fatigue or dynamic safety; use the relevant load cases, standards, and engineering review."),
        ("analytical", 2, "A component meets its mean tolerance, but production failures cluster near one end of the tolerance range. What is the strongest quality response?", ["Examine the process distribution, capability, measurement system, and failure mechanism before changing limits.", "Widen the tolerance until failures fall.", "Inspect only the mean because it is on target.", "Remove edge measurements as outliers."], 0, "A centered mean can hide spread, measurement issues, or a mechanism near tolerance boundaries."),
        ("detail", 3, "A field modification fixes an observed fault but has not been checked against the original certification and downstream interfaces. What is required before release?", ["Document the change, assess system-level hazards and interfaces, and obtain required qualified verification and approvals.", "Release to the field because the original fault is resolved.", "Ask the installer to decide whether certification still applies.", "Test only the modified component under nominal conditions."], 0, "A local fix can introduce system hazards or invalidate approvals; change control, interface assessment, and qualified verification are necessary."),
    ],
    "science": [
        ("analytical", 1, "A field study finds a pollutant is higher downstream, but sampling occurred after rain only at the downstream site. What is the key next step?", ["Use matched upstream/downstream sampling across comparable conditions and measure relevant flow and timing.", "Report the downstream value as the source concentration.", "Collect more downstream samples after rain.", "Compare the value with a national average from a different season."], 0, "Location, timing, rainfall, and flow are confounded; matched sampling is needed to evaluate a source-related difference."),
        ("detail", 2, "A laboratory result is near the detection limit and was measured in one batch without blanks. What should temper its interpretation?", ["Treat it as uncertain and review method limits, blanks, replication, and contamination controls.", "Round it to zero because it is small.", "Report it as precise because the instrument produced a number.", "Repeat the reading until the same value appears."], 0, "Near-limit results need method and contamination controls; a numerical reading alone does not establish reliable detection."),
        ("analytical", 3, "A crop trial reports higher yield for a new variety, but plots were not randomized across a strong soil gradient. Which analysis is strongest?", ["Use the layout and soil measurements to assess confounding, and replicate with randomized or blocked allocation.", "Compare the maximum yield from each variety.", "Adjust only for total rainfall across the farm.", "Conclude the variety caused the increase because both were grown in the same year."], 0, "A soil gradient can confound variety and yield; blocking/randomization and suitable covariates improve attribution."),
    ],
    "education": [
        ("people", 1, "A learner answers a familiar problem correctly but cannot transfer the method to a new context. What assessment best distinguishes memorization from understanding?", ["Use a novel but aligned problem and ask the learner to justify each step.", "Repeat the same problem with different numbers.", "Increase the time limit on the familiar problem.", "Ask whether the learner feels confident."], 0, "A novel transfer task with reasoning tests whether the learner can apply the concept beyond a rehearsed example."),
        ("analytical", 2, "A class's mean score rises after an intervention, while lower-performing learners show no gain. Which report is most informative?", ["Show distributions and subgroup uncertainty, then examine implementation and access differences.", "Report the mean alone because it is the standard summary.", "Remove the lower-performing learners as non-responders.", "Conclude the intervention works only for high scorers."], 0, "An average can hide distributional effects; subgroup trends and implementation context guide fair interpretation."),
        ("detail", 3, "A teacher changes both the lesson method and grading rubric, then scores improve. What prevents a confident claim about the teaching method?", ["The rubric change alters the measurement; use a stable, valid measure or independently assess comparable work.", "Improvement proves the new method was effective.", "A larger class automatically separates the two changes.", "Average the old and new rubric scores."], 0, "Changing the outcome measure alongside the instruction confounds the observed score improvement."),
    ],
    "public_service": [
        ("detail", 1, "A rule appears to permit an action, but the document is from another jurisdiction and predates a later amendment. What is the correct next step?", ["Verify the current primary authority and effective date in the relevant jurisdiction before applying it.", "Use the rule because the wording is clear.", "Combine the older rule with the newer summary.", "Rely on a search result that quotes the rule."], 0, "Legal and policy authority depends on jurisdiction, hierarchy, and date; verify current primary sources."),
        ("people", 2, "An outreach program has low participation in one community despite eligibility. Which response best avoids blaming the community for the result?", ["Investigate access barriers with affected people and compare delivery, trust, language, and eligibility processes.", "Increase outreach volume using the same channel.", "Redefine participation so initial contact counts as success.", "Conclude the service is not needed because demand is low."], 0, "Low uptake can signal design or access barriers; investigate the service pathway with the people affected."),
        ("analytical", 3, "A policy's overall benefit is positive, but costs and benefits fall on different groups and some costs are hard to quantify. What is the most complete appraisal?", ["Show distributional impacts, assumptions, non-monetized effects, uncertainty, and who bears each cost.", "Use the net total because distribution is a separate issue.", "Convert every effect to money using one fixed value.", "Exclude unquantified effects to avoid subjective judgments."], 0, "A net total hides distribution and omitted outcomes; transparent assumptions and non-monetized effects are part of a complete appraisal."),
    ],
    "media": [
        ("detail", 1, "A viral post contains a genuine image, but its caption claims it was taken this week in another country. Which verification is strongest?", ["Trace the earliest available source and verify date and location using independent contextual evidence.", "Use reverse-image search alone as proof of the caption.", "Check whether several reposts use the same caption.", "Accept it if the image itself has not been edited."], 0, "An authentic image can be miscaptioned; provenance, date, and location need independent verification."),
        ("analytical", 2, "A headline says a risk doubled, from 1 case per 100,000 to 2 per 100,000. What context is necessary?", ["Give the absolute rates, population and time period, uncertainty, and comparison basis.", "Avoid reporting the rates because relative risk is clearer.", "State that the risk is now high because it doubled.", "Compare the new rate with a different population's baseline."], 0, "Relative change can sound large while absolute risk remains small; both denominators and uncertainty matter."),
        ("communication", 3, "A source grants an interview on background, while another source disputes a central claim and records conflict. How should a report handle the evidence?", ["Clarify attribution terms, corroborate the claim independently, disclose material uncertainty, and seek a response.", "Publish the most detailed account without checking its attribution conditions.", "Omit the disputed source because it creates ambiguity.", "Present both claims as equally reliable without checking evidence."], 0, "Attribution agreements and evidence quality must be respected; corroboration, uncertainty, and a fair response matter."),
    ],
    "hospitality": [
        ("practical", 1, "A kitchen's cooling log is missing for a batch of high-risk food, though it smells normal. What is the safe decision?", ["Follow local food-safety rules and the site's discard/escalation procedure; smell is not a safety test.", "Serve it if it is reheated thoroughly.", "Estimate the cooling time from the next batch.", "Keep it chilled now and assume the earlier cooling was safe."], 0, "Sensory checks cannot establish safe time-temperature control; follow applicable procedures for missing records."),
        ("organization", 2, "A service team meets average ticket time, but the longest waits occur during a recurring handoff bottleneck. Which change should be tested first?", ["Map arrivals and handoffs by time, then pilot a targeted staffing or workflow change and track wait distribution.", "Reduce every ticket-time target by the same amount.", "Add staff to the busiest station without measuring the handoff.", "Report the average because the target was met."], 0, "Segmented waits reveal a bottleneck that the mean hides; a targeted pilot tests whether the handoff causes the delay."),
        ("analytical", 3, "A restaurant's promotion increases order count, while contribution margin falls and waste rises. Which evaluation best informs whether to repeat it?", ["Calculate incremental contribution after discounts, variable costs, cannibalization, and waste against a suitable baseline.", "Repeat it because order volume is higher.", "Compare gross sales with a normal weekday.", "Exclude waste because it is an operational measure."], 0, "Volume alone omits profitability; incremental margin, displaced sales, costs, and waste determine the promotion's net effect."),
    ],
}


def _career_track(career):
    career_id = career.get("id") if career else ""
    for track, career_ids in _CAREER_TRACKS.items():
        if career_id in career_ids:
            return track
    return "business"


def _questions_for_track(track):
    questions = []
    for dimension, level, prompt, options, answer, explanation in _DOMAIN_QUESTION_BANK[
        track
    ]:
        questions.append(
            {
                "dimension": dimension,
                "level": level,
                "track": track,
                "prompt": prompt,
                "options": options,
                "answer": answer,
                "explanation": explanation,
            }
        )
    return questions


def _question_priority(question, skill_profile, practiced_dimensions, seen_dimensions):
    dimension = question["dimension"]
    return (
        dimension not in seen_dimensions,
        dimension in practiced_dimensions,
        100 - skill_profile.get(dimension, 50),
    )


def build_learning_test(
    career,
    completed_task_count,
    previous_average,
    attempt_id,
    skill_profile=None,
    completed_task_ids=(),
):
    level = 3 if completed_task_count >= 8 or previous_average >= 80 else (
        2 if completed_task_count >= 3 or previous_average >= 60 else 1
    )
    track = _career_track(career)
    domain_questions = [
        question for question in _questions_for_track(track)
        if question["level"] <= level
    ]
    common_questions = [
        question for question in _COMMON_QUESTIONS
        if question["level"] <= level
    ]
    if len(domain_questions) < level or len(common_questions) < 10 - level:
        raise RuntimeError(f"Learning test bank has too few questions for level {level}.")

    skill_profile = skill_profile or {}
    task_focus = {
        task["focus"]
        for task in tasks_for_career(career)
        if task["id"] in set(completed_task_ids)
    }
    rng = random.Random(attempt_id)
    selected = []
    seen_dimensions = set()
    for pool, target_count in ((domain_questions, level), (common_questions, 10 - level)):
        remaining = list(pool)
        while remaining and sum(item in pool for item in selected) < target_count:
            remaining.sort(
                key=lambda question: (
                    *_question_priority(
                        question, skill_profile, task_focus, seen_dimensions
                    ),
                    rng.random(),
                ),
                reverse=True,
            )
            question = remaining.pop(0)
            selected.append(question)
            seen_dimensions.add(question["dimension"])

    rng.shuffle(selected)
    career_title = career["title"] if career else "your chosen career"
    prepared_questions = []
    for question in selected:
        options = list(question["options"])
        correct_answer = options[question["answer"]]
        rng.shuffle(options)
        prepared_questions.append(
            {
                **question,
                "prompt": question["prompt"].format(career=career_title),
                "options": options,
                "answer": options.index(correct_answer),
            }
        )
    return {"level": level, "questions": prepared_questions}


def grade_learning_test(questions, submitted_answers):
    answers = {}
    correct = 0
    mistakes = []
    analysis = []
    for index, question in enumerate(questions):
        answer = submitted_answers.get(str(index), "")
        try:
            answer_index = int(answer)
        except (TypeError, ValueError):
            answer_index = -1
        if answer_index not in range(len(question["options"])):
            answer_index = -1
        answers[str(index)] = answer_index
        is_correct = answer_index == question["answer"]
        correct += is_correct
        review_item = {
            "prompt": question["prompt"],
            "selected": (
                question["options"][answer_index] if answer_index >= 0 else "No answer"
            ),
            "correct": question["options"][question["answer"]],
            "explanation": question["explanation"],
            "dimension": question["dimension"],
            "is_correct": is_correct,
        }
        analysis.append(review_item)
        if not is_correct:
            mistakes.append(review_item)
    return {
        "answers": answers,
        "correct": correct,
        "total": len(questions),
        "score": round(correct / len(questions) * 100) if questions else 0,
        "mistakes": mistakes,
        "questions": analysis,
    }
