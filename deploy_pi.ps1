# deploy_pi.ps1
# Helper script to deploy SongiBot to your Raspberry Pi

$PiIP = "172.31.17.70"
$PiUser = "sb"
$RemoteDir = "/home/sb/SongiBot"

Write-Host "Deploying SongiBot to Raspberry Pi ($PiUser@$PiIP)..." -ForegroundColor Cyan

# Check if SSH is reachable
Write-Host "Checking network connection to Raspberry Pi..."
if (Test-Connection -ComputerName $PiIP -Count 1 -Quiet) {
    Write-Host "Pi is reachable." -ForegroundColor Green
} else {
    Write-Host "Error: Cannot ping Raspberry Pi. Check the IP address or network connection." -ForegroundColor Red
    Exit
}

# Transfer files using scp
Write-Host "Copying files to $RemoteDir..." -ForegroundColor Yellow
scp -r ./* "${PiUser}@${PiIP}:${RemoteDir}"

if ($LASTEXITCODE -eq 0) {
    Write-Host "Files copied successfully!" -ForegroundColor Green
    Write-Host "To run the assistant, SSH into the Pi using:" -ForegroundColor Yellow
    Write-Host "  ssh ${PiUser}@${PiIP}"
    Write-Host "Then navigate to the folder and run:" -ForegroundColor Yellow
    Write-Host "  cd ${RemoteDir}"
    Write-Host "  pip3 install -r requirements.txt"
    Write-Host "  python3 app.py"
} else {
    Write-Host "Error: File transfer failed. Please verify SSH credentials." -ForegroundColor Red
}
