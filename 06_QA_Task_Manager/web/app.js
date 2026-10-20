const $ = (id) => document.getElementById(id);
const state = { loadedKey: "", loadedSubtaskParentKey: "" };

const chineseMonths = ["一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月"];

function formatJiraDate(value) {
  if (!value) return "尚未選擇";
  const [year, month, day] = value.split("-").map(Number);
  return `${day}/${chineseMonths[month - 1]}/${String(year).slice(-2)}`;
}

function setBusy(button, busy, busyText, normalText) {
  button.disabled = busy;
  button.textContent = busy ? busyText : normalText;
}

function showError(message) {
  $("successBox").classList.add("hidden");
  $("statusBox").textContent = message;
  $("statusBox").classList.remove("hidden");
}

function clearMessages() {
  $("statusBox").classList.add("hidden");
  $("successBox").classList.add("hidden");
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (response.status === 401 && path !== "/api/login") showLogin();
  if (!response.ok) throw new Error(data.error || `請求失敗（${response.status}）`);
  return data;
}

function showLogin() {
  $("appShell").classList.add("hidden");
  $("loginView").classList.remove("hidden");
  $("loginToken").value = "";
  $("loginUsername").value = localStorage.getItem("qaRememberedUsername") || "";
}

async function showApp(user) {
  $("currentUser").textContent = user.display_name === user.username ? user.username : `${user.display_name}（${user.username}）`;
  $("loginView").classList.add("hidden");
  $("appShell").classList.remove("hidden");
  const config = await request("/api/config");
  $("epicLink").replaceChildren(new Option("請選擇", ""));
  $("testerList").replaceChildren();
    $("qaAssignee").value = config.qa_assignee;
    for (const epic of config.epic_links) {
      const option = document.createElement("option");
      option.value = epic;
      option.textContent = epic;
      $("epicLink").append(option);
    }
    for (const tester of config.testers || []) {
      const label = document.createElement("label");
      label.className = "tester-option";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.name = "tester";
      checkbox.value = tester.username;
      checkbox.addEventListener("change", updateSelectedMembers);
      const name = document.createElement("span");
      name.className = "tester-name";
      name.textContent = tester.username;
      label.append(checkbox, name);
      $("testerList").append(label);
    }
}

async function initialize() {
  try {
    const session = await request("/api/session");
    if (session.authenticated) {
      await showApp(session);
    } else {
      showLogin();
    }
  } catch (error) {
    showLogin();
    $("loginStatus").textContent = error.message;
    $("loginStatus").classList.remove("hidden");
  }
}

async function login() {
  const username = $("loginUsername").value.trim();
  const token = $("loginToken").value.trim();
  const remember = $("rememberLogin").checked;
  $("loginStatus").classList.add("hidden");
  $("loginStatus").classList.remove("pending");
  if (!username) {
    $("loginStatus").textContent = "請輸入 Jira 帳號。";
    return $("loginStatus").classList.remove("hidden");
  }
  if (!token) {
    $("loginStatus").textContent = "請輸入 Jira Token。";
    return $("loginStatus").classList.remove("hidden");
  }
  setBusy($("loginButton"), true, "登入中…", "登入 Jira");
  $("loginStatus").textContent = "正在連線 Jira 並驗證 Token，最多約 15 秒…";
  $("loginStatus").classList.add("pending");
  $("loginStatus").classList.remove("hidden");
  try {
    const user = await request("/api/login", {
      method: "POST",
      body: JSON.stringify({username, token, remember}),
    });
    if (remember) localStorage.setItem("qaRememberedUsername", user.username);
    else localStorage.removeItem("qaRememberedUsername");
    $("loginToken").value = "";
    await showApp(user);
  } catch (error) {
    $("loginToken").value = "";
    $("loginStatus").classList.remove("pending");
    $("loginStatus").textContent = error.message;
    $("loginStatus").classList.remove("hidden");
  } finally {
    setBusy($("loginButton"), false, "登入中…", "登入 Jira");
  }
}

async function logout() {
  try {
    await request("/api/logout", {method: "POST", body: "{}"});
  } finally {
    localStorage.removeItem("qaRememberedUsername");
    $("rememberLogin").checked = false;
    showLogin();
  }
}

async function loadMainIssue() {
  const issueKey = $("mainIssueKey").value.trim().toUpperCase();
  if (!issueKey) return showError("請輸入主任務單號。");
  clearMessages();
  setBusy($("loadButton"), true, "讀取中…", "讀取主任務");
  try {
    const data = await request("/api/load-main", {
      method: "POST",
      body: JSON.stringify({ issue_key: issueKey }),
    });
    state.loadedKey = data.main_issue_key;
    $("mainIssueKey").value = data.main_issue_key;
    $("mainIssueLink").href = data.main_issue_url;
    $("summary").value = data.summary || "";
    $("bugAssignee").value = data.bug_assignee || "";
    $("qaAssignee").value = data.qa_assignee;
    $("environment").value = data.environment || "";
    $("version").value = data.version || "";
    $("testItems").value = data.test_items || "";
    $("agent").value = data.agent || "";
    $("missionPanel").classList.remove("hidden");
  } catch (error) {
    state.loadedKey = "";
    $("missionPanel").classList.add("hidden");
    showError(error.message);
  } finally {
    setBusy($("loadButton"), false, "讀取中…", "讀取主任務");
  }
}

async function createMission() {
  clearMessages();
  const currentKey = $("mainIssueKey").value.trim().toUpperCase();
  if (!state.loadedKey || currentKey !== state.loadedKey) return showError("請先讀取目前的主任務。");
  const payload = {
    main_issue_key: state.loadedKey,
    test_cases: $("testCases").value.trim(),
    start_date: $("startDate").value,
    due_date: $("dueDate").value,
    epic_link: $("epicLink").value,
    summary: $("summary").value.trim(),
    bug_assignee: $("bugAssignee").value.trim(),
    qa_assignee: $("qaAssignee").value.trim(),
    test_items: $("testItems").value.trim(),
    environment: $("environment").value.trim(),
    version: $("version").value.trim(),
    agent: $("agent").value.trim(),
  };
  if (!payload.summary) return showError("請填入摘要。");
  if (!payload.bug_assignee) return showError("請填入 BUG 指派人。");
  if (!payload.qa_assignee) return showError("請填入 QA 經辦人。");
  if (!payload.test_items) return showError("請填入進測項目。");
  if (!payload.environment) return showError("請填入驗證環境。");
  if (!payload.version) return showError("請填入驗證版號。");
  if (!payload.test_cases) return showError("請填入測試案例。");
  if (!payload.start_date || !payload.due_date) return showError("請選擇 Start Date 與到期日。");
  if (!payload.epic_link) return showError("請選擇 Epic Link。");
  if (!window.confirm(`確定要為 ${state.loadedKey} 建立 QA Mission？`)) return;

  setBusy($("createButton"), true, "建立中…", "建立 QA Mission");
  try {
    const result = await request("/api/create", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    $("createdKey").textContent = result.key;
    $("createdLink").href = result.url;
    $("successBox").classList.remove("hidden");
    $("subtaskParentKey").value = result.key;
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy($("createButton"), false, "建立中…", "建立 QA Mission");
  }
}

function clearSubtaskMessages() {
  $("subtaskStatusBox").classList.add("hidden");
  $("subtaskSuccessBox").classList.add("hidden");
}

function showSubtaskError(message) {
  $("subtaskSuccessBox").classList.add("hidden");
  $("subtaskStatusBox").textContent = message;
  $("subtaskStatusBox").classList.remove("hidden");
}

function selectedMembers() {
  return [...document.querySelectorAll('input[name="tester"]:checked')].map((input) => input.value);
}

function updateSelectedMembers() {
  const count = selectedMembers().length;
  $("selectedMembersNote").textContent = count ? `已選擇 ${count} 位，將建立 ${count} 張子任務` : "尚未選擇測試人員";
}

async function loadSubtaskParent() {
  const parentKey = $("subtaskParentKey").value.trim().toUpperCase();
  if (!parentKey) return showSubtaskError("請輸入 QA 主單號。");
  clearSubtaskMessages();
  setBusy($("loadSubtaskParentButton"), true, "讀取中…", "讀取 QA 主單");
  try {
    const data = await request("/api/load-subtask-parent", {
      method: "POST",
      body: JSON.stringify({ parent_key: parentKey }),
    });
    state.loadedSubtaskParentKey = data.parent_key;
    $("subtaskParentKey").value = data.parent_key;
    $("subtaskParentSummary").textContent = data.summary || "—";
    $("subtaskParentDates").textContent = `Start Date：${data.start_date || "未設定"}　到期日：${data.due_date || "未設定"}`;
    $("subtaskParentLink").href = data.parent_url;
    $("subtaskParentPanel").classList.remove("hidden");
  } catch (error) {
    state.loadedSubtaskParentKey = "";
    $("subtaskParentPanel").classList.add("hidden");
    showSubtaskError(error.message);
  } finally {
    setBusy($("loadSubtaskParentButton"), false, "讀取中…", "讀取 QA 主單");
  }
}

async function createSubtasks() {
  clearSubtaskMessages();
  const currentKey = $("subtaskParentKey").value.trim().toUpperCase();
  if (!state.loadedSubtaskParentKey || currentKey !== state.loadedSubtaskParentKey) {
    return showSubtaskError("請先讀取目前的 QA 主單。");
  }
  const payload = {
    parent_key: state.loadedSubtaskParentKey,
    members: selectedMembers(),
    original_estimate: $("originalEstimate").value.trim(),
    remaining_estimate: $("remainingEstimate").value.trim(),
    deadline: $("subtaskDeadline").value,
  };
  if (!payload.members.length) return showSubtaskError("請至少選擇一位測試人員。");
  if (!payload.original_estimate) return showSubtaskError("請填入原始預估時間。");
  if (!payload.remaining_estimate) return showSubtaskError("請填入剩餘時間。");
  if (!payload.deadline) return showSubtaskError("請選擇 Deadline。");
  if (!window.confirm(`確定要在 ${state.loadedSubtaskParentKey} 下建立 ${payload.members.length} 張子任務？\nDeadline：${payload.deadline}\n\n${payload.members.join("、")}`)) return;

  setBusy($("createSubtaskButton"), true, `正在建立 ${payload.members.length} 張…`, "建立所選子任務");
  try {
    const result = await request("/api/create-subtasks", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    $("createdSubtaskList").replaceChildren();
    for (const item of result.created) {
      const link = document.createElement("a");
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = `${item.username}：${item.key} ↗`;
      $("createdSubtaskList").append(link);
    }
    if (result.created.length) $("subtaskSuccessBox").classList.remove("hidden");
    if (result.mattermost?.sent) {
      const notice = document.createElement("span");
      const [, month, day] = result.mattermost.deadline.split("-").map(Number);
      notice.textContent = `Mattermost 已通知 bot_dev，期限 ${month}/${day}`;
      $("createdSubtaskList").append(notice);
    } else if (result.created.length && result.mattermost?.configured === false) {
      $("subtaskStatusBox").textContent = "子任務已建立，但 Mattermost 機器人尚未完成本機 Token 設定。";
      $("subtaskStatusBox").classList.remove("hidden");
    } else if (result.created.length && result.mattermost?.error) {
      $("subtaskStatusBox").textContent = `子任務已建立，但 Mattermost 通知失敗：${result.mattermost.error}`;
      $("subtaskStatusBox").classList.remove("hidden");
    }
    if (result.errors.length) {
      const prefix = $("subtaskStatusBox").classList.contains("hidden") ? "" : `${$("subtaskStatusBox").textContent}\n\n`;
      $("subtaskStatusBox").textContent = prefix + "部分子任務建立失敗：\n" + result.errors.map((item) => `${item.username}：${item.error}`).join("\n");
      $("subtaskStatusBox").classList.remove("hidden");
    }
  } catch (error) {
    showSubtaskError(error.message);
  } finally {
    setBusy($("createSubtaskButton"), false, "建立中…", "建立所選子任務");
  }
}

$("loadButton").addEventListener("click", loadMainIssue);
$("loginButton").addEventListener("click", login);
$("loginToken").addEventListener("keydown", (event) => {
  if (event.key === "Enter") login();
});
$("logoutButton").addEventListener("click", logout);
$("mainIssueKey").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadMainIssue();
});
$("createButton").addEventListener("click", createMission);
$("loadSubtaskParentButton").addEventListener("click", loadSubtaskParent);
$("subtaskParentKey").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadSubtaskParent();
});
$("createSubtaskButton").addEventListener("click", createSubtasks);
$("clearMembersButton").addEventListener("click", () => {
  document.querySelectorAll('input[name="tester"]:checked').forEach((input) => { input.checked = false; });
  updateSelectedMembers();
});
$("startDate").addEventListener("change", (event) => {
  $("startDateDisplay").textContent = formatJiraDate(event.target.value);
});
$("dueDate").addEventListener("change", (event) => {
  $("dueDateDisplay").textContent = formatJiraDate(event.target.value);
});

initialize();
