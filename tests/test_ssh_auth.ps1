# Test SSH authentication to HP/Aruba switch
$host_ip = "10.4.20.65"
$username = "manager"
$password = "SY=ojE3%'_s"

Write-Host "`n=== Testing SSH Authentication ===" -ForegroundColor Cyan
Write-Host "Host: $host_ip" -ForegroundColor White
Write-Host "Username: $username" -ForegroundColor White
Write-Host "Password length: $($password.Length) chars" -ForegroundColor White
Write-Host ""

# Test with plink (PuTTY command line) if available
if (Get-Command plink -ErrorAction SilentlyContinue) {
    Write-Host "Testing with plink..." -ForegroundColor Yellow
    $output = echo y | plink -ssh -l $username -pw $password $host_ip "show version" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ SUCCESS with plink" -ForegroundColor Green
        Write-Host "Output:" -ForegroundColor Gray
        Write-Host $output
    } else {
        Write-Host "❌ FAILED with plink (exit code: $LASTEXITCODE)" -ForegroundColor Red
        Write-Host "Error: $output" -ForegroundColor Red
    }
    Write-Host ""
}

# Test with ssh.exe (Windows 10+ built-in)
if (Get-Command ssh -ErrorAction SilentlyContinue) {
    Write-Host "Testing with ssh.exe..." -ForegroundColor Yellow
    
    # Create a temporary expect script for password
    $expectScript = @"
#!/usr/bin/expect -f
set timeout 20
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ${username}@${host_ip}
expect "password:"
send "${password}\r"
expect "#"
send "show version\r"
expect "#"
send "exit\r"
expect eof
"@
    
    # Try direct SSH with password via sshpass if available
    $env:SSHPASS = $password
    $sshCommand = "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o PubkeyAuthentication=no ${username}@${host_ip} 'show version'"
    
    Write-Host "Command: ssh ${username}@${host_ip}" -ForegroundColor Gray
    Write-Host "Note: Windows ssh.exe requires interactive password entry or key-based auth" -ForegroundColor Yellow
    Write-Host "Attempting connection (you may need to enter password manually)..." -ForegroundColor Yellow
    
    # Since we can't easily automate password with Windows ssh, let's just test connectivity
    $result = Test-NetConnection -ComputerName $host_ip -Port 22 -InformationLevel Quiet -WarningAction SilentlyContinue
    
    if ($result) {
        Write-Host "✅ Port 22 is OPEN on $host_ip" -ForegroundColor Green
        Write-Host "SSH service is accessible" -ForegroundColor Green
    } else {
        Write-Host "❌ Port 22 is CLOSED or filtered on $host_ip" -ForegroundColor Red
        Write-Host "Network connectivity issue" -ForegroundColor Red
    }
    Write-Host ""
}

# Test network connectivity
Write-Host "Testing network connectivity..." -ForegroundColor Yellow
$ping = Test-Connection -ComputerName $host_ip -Count 2 -Quiet
if ($ping) {
    Write-Host "✅ Host $host_ip is reachable (ping successful)" -ForegroundColor Green
} else {
    Write-Host "❌ Host $host_ip is NOT reachable (ping failed)" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Credential Details ===" -ForegroundColor Cyan
Write-Host "Username: '$username'" -ForegroundColor White
Write-Host "Password: '$password'" -ForegroundColor White
Write-Host "Password (hex): " -NoNewline -ForegroundColor White
[System.Text.Encoding]::UTF8.GetBytes($password) | ForEach-Object { Write-Host -NoNewline ("{0:X2} " -f $_) -ForegroundColor Gray }
Write-Host ""
Write-Host ""

Write-Host "=== Special Characters in Password ===" -ForegroundColor Cyan
$specialChars = @()
for ($i = 0; $i -lt $password.Length; $i++) {
    $char = $password[$i]
    if ($char -match '[^a-zA-Z0-9]') {
        $specialChars += "Position $i`: '$char' (ASCII: $([int][char]$char))"
    }
}
if ($specialChars.Count -gt 0) {
    Write-Host "Found special characters:" -ForegroundColor Yellow
    $specialChars | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    Write-Host ""
    Write-Host "These characters might need escaping in some contexts:" -ForegroundColor Yellow
    Write-Host "  = (equals sign)" -ForegroundColor Gray
    Write-Host "  % (percent sign)" -ForegroundColor Gray
    Write-Host "  ' (single quote)" -ForegroundColor Gray
    Write-Host "  _ (underscore - usually safe)" -ForegroundColor Gray
} else {
    Write-Host "No special characters found" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "If authentication is failing in Python/Paramiko:" -ForegroundColor White
Write-Host "1. Verify the password is exactly: SY=ojE3%'_s" -ForegroundColor Yellow
Write-Host "2. Check if SSH is enabled on the switch" -ForegroundColor Yellow
Write-Host "3. Verify the username is 'manager' (case-sensitive)" -ForegroundColor Yellow
Write-Host "4. Some switches require specific SSH ciphers/algorithms" -ForegroundColor Yellow
Write-Host ""
