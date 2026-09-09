$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

trap {
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$BaseUrl = if ($env:JIRA_BASE_URL) { $env:JIRA_BASE_URL } else { "https://pmo-jira.qyrc452.com" }
$Token = if ($env:JIRA_API_TOKEN) { $env:JIRA_API_TOKEN } else { "" }
$Project = if ($env:JIRA_PROJECT_KEY) { $env:JIRA_PROJECT_KEY } else { "QA" }
$IssueType = if ($env:JIRA_ISSUE_TYPE) { $env:JIRA_ISSUE_TYPE } else { "" }
$AllIssueTypes = [string]::IsNullOrWhiteSpace($IssueType)
$JqlExtra = if ($env:JIRA_JQL_EXTRA) { $env:JIRA_JQL_EXTRA } else { "" }
$SummaryContains = if ($env:JIRA_SUMMARY_CONTAINS) { $env:JIRA_SUMMARY_CONTAINS } else { "" }
$MatchUserSuffix = if ($env:JIRA_MATCH_USER_SUFFIX) { [System.Convert]::ToBoolean($env:JIRA_MATCH_USER_SUFFIX) } else { $true }
$AllowNoSuffixUsersText = if ($env:JIRA_ALLOW_NO_SUFFIX_USERS) { $env:JIRA_ALLOW_NO_SUFFIX_USERS } else { "arsene211" }
$ReportUnit = if ($env:JIRA_REPORT_UNIT) { $env:JIRA_REPORT_UNIT } else { "days" }
$HoursPerDay = if ($env:JIRA_HOURS_PER_DAY) { [double]$env:JIRA_HOURS_PER_DAY } else { 8.0 }
$ReportMode = if ($env:JIRA_REPORT_MODE) { $env:JIRA_REPORT_MODE } else { "bug-count" }
$BugIssueType = if ($env:JIRA_BUG_ISSUE_TYPE) { $env:JIRA_BUG_ISSUE_TYPE } else { "Bug" }
$ApiVersion = if ($env:JIRA_API_VERSION) { $env:JIRA_API_VERSION } else { "2" }
$AuthMode = if ($env:JIRA_AUTH_MODE) { $env:JIRA_AUTH_MODE } else { "bearer" }
$UserAgent = if ($env:JIRA_USER_AGENT) {
    $env:JIRA_USER_AGENT
} else {
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}

$StartDateText = $null
$EndDateText = $null
$ReferenceDateText = $null
$WeekOffset = 0
$Mention = "@all"
$Deadline = "12:00"
$TicketLabel = "TEST"
$NoCsv = $false
$OutputDir = $ScriptDir

$QaUsersOrder = @(
    "arthur734",
    "lisa735",
    "ralflin460",
    "peter210",
    "arsene211",
    "joey209",
    "rose603",
    "morris706",
    "leo296",
    "mincy295",
    "ben654",
    "lydia736",
    "lily265"
)

$QaUserSuffix = @{
    arthur734 = "Arthur"
    lisa735 = "Lisa"
    ralflin460 = "Ralf"
    peter210 = "Peter"
    arsene211 = "Arsene"
    joey209 = "Joey"
    rose603 = "Rose"
    morris706 = "Morris"
    leo296 = "Leo"
    mincy295 = "Mincy"
    ben654 = "Ben"
    lydia736 = "Lydia"
    lily265 = "Lily"
}

$AllowNoSuffixUsers = New-Object System.Collections.Generic.HashSet[string]
foreach ($user in ($AllowNoSuffixUsersText -split ",")) {
    $cleanUser = $user.Trim().ToLowerInvariant()
    if ($cleanUser) {
        [void]$AllowNoSuffixUsers.Add($cleanUser)
    }
}

function Show-Help {
    @"
用法:
  .\run_jira_report.bat --start 2026-06-26 --end 2026-07-02
  .\run_jira_report.bat --week-offset -1
  .\run_jira_report.bat

必要設定:
  `$env:JIRA_API_TOKEN="你的真正 Jira token"

參數:
  --start YYYY-MM-DD          自訂起日
  --end YYYY-MM-DD            自訂迄日
  --reference-date YYYY-MM-DD 用此日期推算週五到週四
  --week-offset N             0 本週，-1 上週，1 下週
  --mention TEXT              預設 @all
  --deadline TEXT             預設 12:00
  --ticket-label TEXT         預設 TEST
  --no-csv                    不輸出 CSV
  --output-dir PATH           CSV 輸出資料夾
  --base-url URL              Jira base URL
  --project KEY               Jira project key，預設 QA
  --issue-type TYPE           限制 Jira issue type，例如 Task、Test
  --all-issue-types           不限制 issue type
  --summary-contains TEXT     只統計標題包含此文字的單，例如 [QA] 或 TEST
  --no-user-suffix-filter     不限制單名結尾必須是 _人名
  --allow-no-suffix-users CSV 允許沒有 _人名 尾綴的人員帳號，預設 arsene211
  --unit UNIT                 輸出單位：days=8小時顯示1.0，hours=實際小時。預設 days
  --hours-per-day N           days 單位換算基準，預設 8
  --report-mode MODE          bug-count=開單數量，worklog=log 時數。預設 bug-count
  --bug-issue-type TYPE       限制 issue type；不指定則統計全部 QA 單
  --jql-extra JQL             額外 JQL 條件，例如 labels = weekly
  --auth-mode MODE            bearer 或 basic_base64
  --help                      顯示說明
"@
}

function Get-RequiredValue {
    param(
        [string[]] $Items,
        [int] $Index,
        [string] $Name
    )

    if ($Index + 1 -ge $Items.Count) {
        throw "$Name 後面需要一個值。"
    }

    return $Items[$Index + 1]
}

for ($i = 0; $i -lt $args.Count; $i++) {
    $arg = $args[$i]
    switch ($arg) {
        "--help" { Show-Help; exit 0 }
        "-h" { Show-Help; exit 0 }
        "--start" { $StartDateText = Get-RequiredValue $args $i $arg; $i++ }
        "--end" { $EndDateText = Get-RequiredValue $args $i $arg; $i++ }
        "--reference-date" { $ReferenceDateText = Get-RequiredValue $args $i $arg; $i++ }
        "--week-offset" { $WeekOffset = [int](Get-RequiredValue $args $i $arg); $i++ }
        "--mention" { $Mention = Get-RequiredValue $args $i $arg; $i++ }
        "--deadline" { $Deadline = Get-RequiredValue $args $i $arg; $i++ }
        "--ticket-label" { $TicketLabel = Get-RequiredValue $args $i $arg; $i++ }
        "--no-csv" { $NoCsv = $true }
        "--output-dir" { $OutputDir = Get-RequiredValue $args $i $arg; $i++ }
        "--base-url" { $BaseUrl = Get-RequiredValue $args $i $arg; $i++ }
        "--token" { $Token = Get-RequiredValue $args $i $arg; $i++ }
        "--project" { $Project = Get-RequiredValue $args $i $arg; $i++ }
        "--issue-type" { $IssueType = Get-RequiredValue $args $i $arg; $AllIssueTypes = $false; $i++ }
        "--all-issue-types" { $AllIssueTypes = $true }
        "--summary-contains" { $SummaryContains = Get-RequiredValue $args $i $arg; $i++ }
        "--no-user-suffix-filter" { $MatchUserSuffix = $false }
        "--allow-no-suffix-users" {
            $AllowNoSuffixUsers.Clear()
            $AllowNoSuffixUsersText = Get-RequiredValue $args $i $arg
            foreach ($user in ($AllowNoSuffixUsersText -split ",")) {
                $cleanUser = $user.Trim().ToLowerInvariant()
                if ($cleanUser) {
                    [void]$AllowNoSuffixUsers.Add($cleanUser)
                }
            }
            $i++
        }
        "--unit" { $ReportUnit = Get-RequiredValue $args $i $arg; $i++ }
        "--hours-per-day" { $HoursPerDay = [double](Get-RequiredValue $args $i $arg); $i++ }
        "--report-mode" { $ReportMode = Get-RequiredValue $args $i $arg; $i++ }
        "--bug-issue-type" { $BugIssueType = Get-RequiredValue $args $i $arg; $i++ }
        "--jql-extra" { $JqlExtra = Get-RequiredValue $args $i $arg; $i++ }
        "--api-version" { $ApiVersion = Get-RequiredValue $args $i $arg; $i++ }
        "--auth-mode" { $AuthMode = Get-RequiredValue $args $i $arg; $i++ }
        "--user-agent" { $UserAgent = Get-RequiredValue $args $i $arg; $i++ }
        default { throw "不認識的參數: $arg。可用 --help 查看用法。" }
    }
}

function Assert-Token {
    param([string] $Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "缺少 Jira token。請先執行 `$env:JIRA_API_TOKEN=`"真正的 Jira token`""
    }

    if ($Value -eq "你的 Jira token" -or $Value -eq "貼上真正的token") {
        throw "你目前還是使用範例文字，請把 JIRA_API_TOKEN 換成真正的 Jira token。"
    }

    foreach ($char in $Value.ToCharArray()) {
        if ([int][char]$char -gt 127) {
            throw "JIRA_API_TOKEN 內含非英文/數字/符號字元，請確認沒有中文、空白或多貼到說明文字。"
        }
    }
}

function Parse-DateOnly {
    param([string] $Text)
    return [datetime]::ParseExact($Text, "yyyy-MM-dd", [System.Globalization.CultureInfo]::InvariantCulture)
}

function New-TaiwanDateTimeOffset {
    param([datetime] $Day)
    return [datetimeoffset]::new($Day.Year, $Day.Month, $Day.Day, 0, 0, 0, [timespan]::FromHours(8))
}

function Get-DateRange {
    if ($StartDateText -or $EndDateText) {
        if (-not $StartDateText -or -not $EndDateText) {
            throw "--start 和 --end 必須一起指定。"
        }

        $startDay = Parse-DateOnly $StartDateText
        $endDay = Parse-DateOnly $EndDateText
        if ($endDay -lt $startDay) {
            throw "--end 不可早於 --start。"
        }

        $start = New-TaiwanDateTimeOffset $startDay
        $end = (New-TaiwanDateTimeOffset $endDay).AddDays(1)
        return @($start, $end)
    }

    $reference = if ($ReferenceDateText) { Parse-DateOnly $ReferenceDateText } else { [datetime]::Now.Date }
    $fridayWeekday = 5
    $daysSinceFriday = (([int]$reference.DayOfWeek - $fridayWeekday) + 7) % 7
    $startDay = $reference.AddDays(-$daysSinceFriday).AddDays(7 * $WeekOffset)
    $start = New-TaiwanDateTimeOffset $startDay
    return @($start, $start.AddDays(7))
}

function Format-ReportDate {
    param([datetimeoffset] $Value)

    $weekdays = @("日", "一", "二", "三", "四", "五", "六")
    $weekday = $weekdays[[int]$Value.DayOfWeek]
    return "{0:yyyy/MM/dd} 星期{1}" -f $Value, $weekday
}

function Join-QueryString {
    param([hashtable] $Params)

    $pairs = foreach ($key in $Params.Keys) {
        "{0}={1}" -f [uri]::EscapeDataString([string]$key), [uri]::EscapeDataString([string]$Params[$key])
    }

    return ($pairs -join "&")
}

function Read-ErrorBody {
    param($Response)

    if (-not $Response) {
        return ""
    }

    try {
        $stream = $Response.GetResponseStream()
        if (-not $stream) {
            return ""
        }
        $reader = [System.IO.StreamReader]::new($stream)
        return $reader.ReadToEnd()
    } catch {
        return ""
    }
}

function Invoke-JiraGet {
    param(
        [string] $Path,
        [hashtable] $Params = @{}
    )

    $uri = "{0}{1}" -f $BaseUrl.TrimEnd("/"), $Path
    if ($Params.Count -gt 0) {
        $uri = "{0}?{1}" -f $uri, (Join-QueryString $Params)
    }

    try {
        return Invoke-RestMethod -Uri $uri -Method Get -Headers $script:Headers -TimeoutSec 60
    } catch {
        $response = $_.Exception.Response
        $statusCode = if ($response) { [int]$response.StatusCode } else { "UNKNOWN" }
        $body = Read-ErrorBody $response

        if ($body -match "cloudflare" -or $body -match "browser_signature_banned" -or $body -match "Error 1010") {
            throw @"
Jira API 被 Cloudflare 擋下。
Status Code: $statusCode
URL: $uri

Cloudflare 回應:
$body

這不是 Jira token 錯誤。請確認你在公司 VPN / 允許的網路內，或請 Jira/Cloudflare 管理員放行 API 存取。
"@
        }

        throw @"
Jira API 呼叫失敗。
Status Code: $statusCode
URL: $uri
Response: $body
"@
    }
}

function Convert-JiraDateTime {
    param([string] $Value)

    $raw = $Value.Trim()
    if ($raw.EndsWith("Z")) {
        $raw = $raw.Substring(0, $raw.Length - 1) + "+00:00"
    }
    $raw = $raw -replace "([+-]\d{2})(\d{2})$", '$1:$2'
    return ([datetimeoffset]::Parse($raw, [System.Globalization.CultureInfo]::InvariantCulture)).ToOffset([timespan]::FromHours(8))
}

function Get-PropertyValue {
    param($Object, [string] $Name)

    if ($null -eq $Object) {
        return $null
    }

    $property = $Object.PSObject.Properties[$Name]
    if ($property) {
        return $property.Value
    }

    return $null
}

function Get-AuthorKeys {
    param($Author)

    $result = New-Object System.Collections.Generic.HashSet[string]
    foreach ($name in @("name", "key", "displayName", "emailAddress", "accountId")) {
        $value = Get-PropertyValue $Author $name
        if (-not $value) {
            continue
        }

        $text = ([string]$value).Trim().ToLowerInvariant()
        if (-not $text) {
            continue
        }

        [void]$result.Add($text)
        if ($text.Contains("@")) {
            [void]$result.Add($text.Split("@")[0])
        }
    }

    return $result
}

function Match-QaUser {
    param($Author)

    $keys = Get-AuthorKeys $Author
    foreach ($user in $QaUsersOrder) {
        if ($keys.Contains($user.ToLowerInvariant())) {
            return $user
        }
    }

    return $null
}

function Test-SummaryMatchesQaUserSuffix {
    param(
        [string] $Summary,
        [string] $QaUser
    )

    if (-not $MatchUserSuffix) {
        return $true
    }

    if ([string]::IsNullOrWhiteSpace($Summary) -or [string]::IsNullOrWhiteSpace($QaUser)) {
        return $false
    }

    if (-not $QaUserSuffix.ContainsKey($QaUser)) {
        return $false
    }

    $suffix = [regex]::Escape([string]$QaUserSuffix[$QaUser])
    if ($Summary.Trim() -match ("(?i)_" + $suffix + "$")) {
        return $true
    }

    return $AllowNoSuffixUsers.Contains($QaUser.ToLowerInvariant())
}

function Match-QaUserFromSummarySuffix {
    param([string] $Summary)

    if ([string]::IsNullOrWhiteSpace($Summary)) {
        return $null
    }

    $cleanSummary = $Summary.Trim()
    foreach ($user in $QaUsersOrder) {
        if (-not $QaUserSuffix.ContainsKey($user)) {
            continue
        }

        $suffix = [regex]::Escape([string]$QaUserSuffix[$user])
        if ($cleanSummary -match ("(?i)_" + $suffix + "$")) {
            return $user
        }
    }

    return $null
}

function Convert-SecondsToReportValue {
    param([int] $Seconds)

    $rawHours = $Seconds / 3600
    switch ($ReportUnit.ToLowerInvariant()) {
        "hours" { return [math]::Round($rawHours, 2) }
        "days" {
            if ($HoursPerDay -le 0) {
                throw "--hours-per-day 必須大於 0。"
            }
            return [math]::Round($rawHours / $HoursPerDay, 2)
        }
        default { throw "--unit 只支援 days 或 hours。" }
    }
}

function Get-IssuesByWorklogDate {
    param(
        [datetimeoffset] $Start,
        [datetimeoffset] $EndExclusive
    )

    $endInclusive = $EndExclusive.AddSeconds(-1)
    $conditions = @(
        ('project = "{0}"' -f $Project)
    )

    if (-not $AllIssueTypes -and -not [string]::IsNullOrWhiteSpace($IssueType)) {
        $conditions += ('issuetype = "{0}"' -f $IssueType)
    }

    $conditions += ('worklogDate >= "{0:yyyy-MM-dd}"' -f $Start)
    $conditions += ('worklogDate <= "{0:yyyy-MM-dd}"' -f $endInclusive)

    if (-not [string]::IsNullOrWhiteSpace($JqlExtra)) {
        $conditions += "($JqlExtra)"
    }

    $jql = "{0} ORDER BY key ASC" -f ($conditions -join " AND ")
    Write-Host "JQL: $jql" -ForegroundColor DarkGray

    $issues = New-Object System.Collections.Generic.List[object]
    $startAt = 0
    $maxResults = 100

    while ($true) {
        $data = Invoke-JiraGet "/rest/api/$ApiVersion/search" @{
            jql = $jql
            startAt = $startAt
            maxResults = $maxResults
            fields = "summary,issuetype"
        }

        $current = @($data.issues)
        foreach ($issue in $current) {
            [void]$issues.Add($issue)
        }

        $total = [int]$data.total
        $startAt += $current.Count
        if ($startAt -ge $total -or $current.Count -eq 0) {
            break
        }
    }

    return $issues
}

function Get-BugIssuesByCreatedDate {
    param(
        [datetimeoffset] $Start,
        [datetimeoffset] $EndExclusive
    )

    $quotedUsers = ($QaUsersOrder | ForEach-Object { '"{0}"' -f $_ }) -join ", "
    $conditions = @(
        ('issuetype = "{0}"' -f $BugIssueType),
        ('project != "{0}"' -f $Project),
        ('reporter in ({0})' -f $quotedUsers),
        ('created >= "{0:yyyy-MM-dd}"' -f $Start),
        ('created < "{0:yyyy-MM-dd}"' -f $EndExclusive)
    )

    if ([string]::IsNullOrWhiteSpace($BugIssueType)) {
        throw "--bug-issue-type 不可為空，開 Bug 單數量統計需要指定 Jira issue type。"
    }

    if (-not [string]::IsNullOrWhiteSpace($JqlExtra)) {
        $conditions += "($JqlExtra)"
    }

    $jql = "{0} ORDER BY key ASC" -f ($conditions -join " AND ")
    Write-Host "JQL: $jql" -ForegroundColor DarkGray

    $issues = New-Object System.Collections.Generic.List[object]
    $startAt = 0
    $maxResults = 100

    while ($true) {
        $data = Invoke-JiraGet "/rest/api/$ApiVersion/search" @{
            jql = $jql
            startAt = $startAt
            maxResults = $maxResults
            fields = "project,summary,issuetype,created,reporter,creator"
        }

        $current = @($data.issues)
        foreach ($issue in $current) {
            [void]$issues.Add($issue)
        }

        $total = [int]$data.total
        $startAt += $current.Count
        if ($startAt -ge $total -or $current.Count -eq 0) {
            break
        }
    }

    return $issues
}

function Get-IssueWorklogs {
    param([string] $IssueKey)

    $worklogs = New-Object System.Collections.Generic.List[object]
    $startAt = 0
    $maxResults = 100

    while ($true) {
        $data = Invoke-JiraGet "/rest/api/$ApiVersion/issue/$IssueKey/worklog" @{
            startAt = $startAt
            maxResults = $maxResults
        }

        $current = @($data.worklogs)
        foreach ($worklog in $current) {
            [void]$worklogs.Add($worklog)
        }

        $total = [int]$data.total
        $startAt += $current.Count
        if ($startAt -ge $total -or $current.Count -eq 0) {
            break
        }
    }

    return $worklogs
}

function Collect-QaWorklogs {
    param(
        [datetimeoffset] $Start,
        [datetimeoffset] $EndExclusive
    )

    $issues = Get-IssuesByWorklogDate $Start $EndExclusive
    Write-Host "找到 issue 數量: $($issues.Count)" -ForegroundColor DarkGray

    $rows = New-Object System.Collections.Generic.List[object]
    for ($i = 0; $i -lt $issues.Count; $i++) {
        $issue = $issues[$i]
        $issueKey = [string]$issue.key
        if (-not $issueKey) {
            continue
        }

        Write-Host ("[{0}/{1}] 讀取 {2} worklog..." -f ($i + 1), $issues.Count, $issueKey) -ForegroundColor DarkGray
        $summary = [string]$issue.fields.summary
        $issueTypeName = if ($issue.fields.issuetype.name) { [string]$issue.fields.issuetype.name } else { "" }
        if (-not [string]::IsNullOrWhiteSpace($SummaryContains)) {
            if ($summary.IndexOf($SummaryContains, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
                continue
            }
        }

        $worklogs = Get-IssueWorklogs $issueKey

        foreach ($worklog in $worklogs) {
            if (-not $worklog.started) {
                continue
            }

            $started = Convert-JiraDateTime ([string]$worklog.started)
            if ($started -lt $Start -or $started -ge $EndExclusive) {
                continue
            }

            $qaUser = Match-QaUser $worklog.author
            if (-not $qaUser) {
                continue
            }

            if (-not (Test-SummaryMatchesQaUserSuffix $summary $qaUser)) {
                continue
            }

            $seconds = [int]$worklog.timeSpentSeconds
            $rawHours = [math]::Round($seconds / 3600, 2)
            $comment = if ($worklog.comment) { ([string]$worklog.comment).Replace("`r", " ").Replace("`n", " ").Trim() } else { "" }
            [void]$rows.Add([pscustomobject]@{
                qa = $qaUser
                issue_key = $issueKey
                issue_type = $issueTypeName
                summary = $summary
                started = $started.ToString("yyyy-MM-dd HH:mm:ss")
                seconds = $seconds
                raw_hours = $rawHours
                hours = Convert-SecondsToReportValue $seconds
                comment = $comment
            })
        }
    }

    return $rows
}

function Collect-BugIssues {
    param(
        [datetimeoffset] $Start,
        [datetimeoffset] $EndExclusive
    )

    $issues = Get-BugIssuesByCreatedDate $Start $EndExclusive
    Write-Host "找到候選 Bug issue 數量: $($issues.Count)" -ForegroundColor DarkGray

    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($issue in $issues) {
        $fields = $issue.fields
        $summary = [string]$fields.summary
        $qaUser = Match-QaUser $fields.reporter
        $ownerField = "reporter"
        if (-not $qaUser) {
            continue
        }

        $created = if ($fields.created) { Convert-JiraDateTime ([string]$fields.created) } else { $null }
        $issueTypeName = if ($fields.issuetype.name) { [string]$fields.issuetype.name } else { "" }
        [void]$rows.Add([pscustomobject]@{
            qa = $qaUser
            project = if ($fields.project.key) { [string]$fields.project.key } else { "" }
            issue_key = [string]$issue.key
            issue_type = $issueTypeName
            summary = $summary
            created = if ($created) { $created.ToString("yyyy-MM-dd HH:mm:ss") } else { "" }
            owner_field = $ownerField
            count = 1
        })
    }

    return $rows
}

function Format-Hour {
    param([double] $Value)

    if ($Value -eq 0) {
        return "0"
    }

    if ($Value % 1 -eq 0) {
        return "{0:0.0}" -f $Value
    }

    return ("{0:0.##}" -f $Value)
}

function Format-Count {
    param([int] $Value)
    return [string]$Value
}

function Build-ThreeColumnTable {
    param([array] $Items)

    $columns = 3
    $rowsPerColumn = [math]::Ceiling($Items.Count / $columns)
    $groups = @()
    for ($i = 0; $i -lt $Items.Count; $i += $rowsPerColumn) {
        $take = [math]::Min($rowsPerColumn, $Items.Count - $i)
        $groups += ,@($Items[$i..($i + $take - 1)])
    }

    $lines = @()
    for ($row = 0; $row -lt $rowsPerColumn; $row++) {
        $cells = @()
        foreach ($group in $groups) {
            if ($row -lt $group.Count) {
                $item = $group[$row]
                $cells += ("{0,-10}: {1,-6}" -f $item.Name, $item.Hour)
            }
        }
        $lines += (($cells -join " | ").TrimEnd())
    }

    return ($lines -join "`n")
}

function Build-BugCountMessage {
    param(
        [hashtable] $CountsByUser,
        [datetimeoffset] $Start,
        [datetimeoffset] $EndExclusive
    )

    $items = @()
    $total = 0
    foreach ($user in $QaUsersOrder) {
        $count = if ($CountsByUser.ContainsKey($user)) { [int]$CountsByUser[$user] } else { 0 }
        $total += $count
        $items += [pscustomobject]@{ Name = $user; Hour = (Format-Count $count) }
    }
    $items += [pscustomobject]@{ Name = "Total"; Hour = (Format-Count $total) }

    $table = Build-ThreeColumnTable $items
    $startText = Format-ReportDate $Start
    $endText = Format-ReportDate $EndExclusive.AddSeconds(-1)

    return @"
$Mention 提醒：本週 Jira Bug 開單數量統計
時間區間：$startText ~ $endText

``````text
$table
``````
"@
}

function Build-SlackMessage {
    param(
        [hashtable] $HoursByUser,
        [datetimeoffset] $Start,
        [datetimeoffset] $EndExclusive
    )

    $items = @()
    $total = 0.0
    foreach ($user in $QaUsersOrder) {
        $hours = if ($HoursByUser.ContainsKey($user)) { [double]$HoursByUser[$user] } else { 0.0 }
        $total += $hours
        $items += [pscustomobject]@{ Name = $user; Hour = (Format-Hour $hours) }
    }
    $items += [pscustomobject]@{ Name = "Total"; Hour = (Format-Hour $total) }

    $table = Build-ThreeColumnTable $items
    $startText = Format-ReportDate $Start
    $endText = Format-ReportDate $EndExclusive.AddSeconds(-1)

    return @"
$Mention 提醒：明天為週報日，請於今日 $Deadline 前完成本週 Jira $TicketLabel 單時數填寫 🦉 🦉 🦉
時間區間：$startText ~ $endText

``````text
$table
``````
"@
}

function Write-CsvFiles {
    param(
        [array] $Rows,
        [hashtable] $HoursByUser,
        [datetimeoffset] $Start,
        [datetimeoffset] $EndExclusive
    )

    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    $startText = $Start.ToString("yyyyMMdd")
    $endText = $EndExclusive.AddSeconds(-1).ToString("yyyyMMdd")
    $detailPath = Join-Path $OutputDir "jira_worklog_detail_${startText}_${endText}.csv"
    $summaryPath = Join-Path $OutputDir "jira_worklog_summary_${startText}_${endText}.csv"

    $detailRows = @($Rows)
    if ($detailRows.Count -gt 0) {
        $detailRows | Export-Csv -Path $detailPath -NoTypeInformation -Encoding UTF8
    } else {
        @(
            [pscustomobject]@{
                qa = ""
                project = ""
                issue_key = ""
                issue_type = ""
                summary = ""
                started = ""
                seconds = ""
                raw_hours = ""
                hours = ""
                comment = ""
            }
        ) | Select-Object -First 0 | Export-Csv -Path $detailPath -NoTypeInformation -Encoding UTF8
    }

    $totalHours = 0.0
    $summaryRows = foreach ($user in $QaUsersOrder) {
        $hours = if ($HoursByUser.ContainsKey($user) -and $null -ne $HoursByUser[$user]) { [double]$HoursByUser[$user] } else { 0.0 }
        $totalHours += $hours
        [pscustomobject]@{ qa = $user; hours = $hours }
    }
    $summaryRows += [pscustomobject]@{ qa = "Total"; hours = [math]::Round($totalHours, 2) }
    $summaryRows | Export-Csv -Path $summaryPath -NoTypeInformation -Encoding UTF8

    Write-Host "已輸出: $detailPath" -ForegroundColor DarkGray
    Write-Host "已輸出: $summaryPath" -ForegroundColor DarkGray
}

function Write-BugCsvFiles {
    param(
        [array] $Rows,
        [hashtable] $CountsByUser,
        [datetimeoffset] $Start,
        [datetimeoffset] $EndExclusive
    )

    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    $startText = $Start.ToString("yyyyMMdd")
    $endText = $EndExclusive.AddSeconds(-1).ToString("yyyyMMdd")
    $detailPath = Join-Path $OutputDir "jira_bug_detail_${startText}_${endText}.csv"
    $summaryPath = Join-Path $OutputDir "jira_bug_summary_${startText}_${endText}.csv"

    $detailRows = @($Rows)
    if ($detailRows.Count -gt 0) {
        $detailRows | Export-Csv -Path $detailPath -NoTypeInformation -Encoding UTF8
    } else {
        @(
            [pscustomobject]@{
                qa = ""
                issue_key = ""
                issue_type = ""
                summary = ""
                created = ""
                owner_field = ""
                count = ""
            }
        ) | Select-Object -First 0 | Export-Csv -Path $detailPath -NoTypeInformation -Encoding UTF8
    }

    $totalCount = 0
    $summaryRows = foreach ($user in $QaUsersOrder) {
        $count = if ($CountsByUser.ContainsKey($user) -and $null -ne $CountsByUser[$user]) { [int]$CountsByUser[$user] } else { 0 }
        $totalCount += $count
        [pscustomobject]@{ qa = $user; count = $count }
    }
    $summaryRows += [pscustomobject]@{ qa = "Total"; count = $totalCount }
    $summaryRows | Export-Csv -Path $summaryPath -NoTypeInformation -Encoding UTF8

    Write-Host "已輸出: $detailPath" -ForegroundColor DarkGray
    Write-Host "已輸出: $summaryPath" -ForegroundColor DarkGray
}

Assert-Token $Token

$authHeader = switch ($AuthMode) {
    "bearer" { "Bearer $Token" }
    "basic_base64" {
        if ($Token.ToLowerInvariant().StartsWith("basic ")) { "Basic $($Token.Substring(6).Trim())" } else { "Basic $Token" }
    }
    default { throw "不支援的 auth mode: $AuthMode。請使用 bearer 或 basic_base64。" }
}

$script:Headers = @{
    Accept = "application/json"
    "Accept-Language" = "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    Authorization = $authHeader
    "Content-Type" = "application/json"
    "User-Agent" = $UserAgent
}

$range = Get-DateRange
$startDt = $range[0]
$endDt = $range[1]

Write-Host "開始拉 Jira QA 報表" -ForegroundColor DarkGray
Write-Host "Jira: $BaseUrl" -ForegroundColor DarkGray
Write-Host "Report mode: $ReportMode" -ForegroundColor DarkGray
if ($ReportMode.ToLowerInvariant() -eq "bug-count") {
    Write-Host "Project: 全部，排除 $Project" -ForegroundColor DarkGray
    Write-Host "Issue type: $BugIssueType" -ForegroundColor DarkGray
    Write-Host "Count by: reporter" -ForegroundColor DarkGray
} elseif ($AllIssueTypes) {
    Write-Host "Issue type: 全部" -ForegroundColor DarkGray
} else {
    Write-Host "Issue type: $IssueType" -ForegroundColor DarkGray
}
if (-not [string]::IsNullOrWhiteSpace($JqlExtra)) {
    Write-Host "Extra JQL: $JqlExtra" -ForegroundColor DarkGray
}
if (-not [string]::IsNullOrWhiteSpace($SummaryContains)) {
    Write-Host "Summary contains: $SummaryContains" -ForegroundColor DarkGray
}
if ($ReportMode.ToLowerInvariant() -eq "worklog" -and $MatchUserSuffix) {
    Write-Host "User suffix filter: 開啟，只統計標題結尾為 _人名 的單" -ForegroundColor DarkGray
    if ($AllowNoSuffixUsers.Count -gt 0) {
        Write-Host "No suffix allowed users: $($AllowNoSuffixUsers -join ', ')" -ForegroundColor DarkGray
    }
} elseif ($ReportMode.ToLowerInvariant() -eq "worklog") {
    Write-Host "User suffix filter: 關閉" -ForegroundColor DarkGray
}
if ($ReportMode.ToLowerInvariant() -eq "worklog" -and $ReportUnit.ToLowerInvariant() -eq "days") {
    Write-Host "Report unit: days，$HoursPerDay 小時 = 1.0" -ForegroundColor DarkGray
} elseif ($ReportMode.ToLowerInvariant() -eq "worklog") {
    Write-Host "Report unit: hours，顯示 Jira 實際小時" -ForegroundColor DarkGray
}
Write-Host "Auth mode: $AuthMode" -ForegroundColor DarkGray
Write-Host ("時間區間: {0} ~ {1}" -f (Format-ReportDate $startDt), (Format-ReportDate $endDt.AddSeconds(-1))) -ForegroundColor DarkGray
Write-Host ("-" * 60) -ForegroundColor DarkGray

$me = Invoke-JiraGet "/rest/api/$ApiVersion/myself"
$meName = if ($me.displayName) { $me.displayName } elseif ($me.name) { $me.name } elseif ($me.emailAddress) { $me.emailAddress } else { "UNKNOWN" }
Write-Host "Jira 登入確認: $meName" -ForegroundColor DarkGray

$mode = $ReportMode.ToLowerInvariant()
switch ($mode) {
    "bug-count" {
        $rows = @(Collect-BugIssues $startDt $endDt)

        $countsByUser = @{}
        foreach ($user in $QaUsersOrder) {
            $countsByUser[$user] = 0
        }
        foreach ($row in $rows) {
            if (-not $countsByUser.ContainsKey($row.qa)) {
                $countsByUser[$row.qa] = 0
            }
            $countsByUser[$row.qa] = [int]$countsByUser[$row.qa] + 1
        }

        Write-Output ""
        Write-Output (Build-BugCountMessage $countsByUser $startDt $endDt)
        Write-Output ""

        if (-not $NoCsv) {
            Write-BugCsvFiles $rows $countsByUser $startDt $endDt
        }
    }
    "worklog" {
        $rows = @(Collect-QaWorklogs $startDt $endDt)

        $hoursByUser = @{}
        foreach ($user in $QaUsersOrder) {
            $hoursByUser[$user] = 0.0
        }
        foreach ($row in $rows) {
            if (-not $hoursByUser.ContainsKey($row.qa)) {
                $hoursByUser[$row.qa] = 0.0
            }
            $hoursByUser[$row.qa] = [math]::Round(([double]$hoursByUser[$row.qa]) + ([double]$row.hours), 2)
        }

        Write-Output ""
        Write-Output (Build-SlackMessage $hoursByUser $startDt $endDt)
        Write-Output ""

        if (-not $NoCsv) {
            Write-CsvFiles $rows $hoursByUser $startDt $endDt
        }
    }
    default {
        throw "--report-mode 只支援 bug-count 或 worklog。"
    }
}
