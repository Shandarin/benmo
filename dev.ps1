[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("help", "config", "up", "down", "logs", "ps", "build", "infra-install", "infra-check", "infra-synth")]
    [string]$Task = "help"
)

$ErrorActionPreference = "Stop"

switch ($Task) {
    "config" { docker compose config --quiet }
    "up" { docker compose up --build -d }
    "down" { docker compose down }
    "logs" { docker compose logs -f --tail=200 }
    "ps" { docker compose ps }
    "build" { docker compose build backend research-worker }
    "infra-install" { npm --prefix infra install }
    "infra-check" { npm --prefix infra run check }
    "infra-synth" { npm --prefix infra run synth }
    default {
        @"
Benmo development tasks
  .\dev.ps1 config         Validate the Compose file
  .\dev.ps1 up             Build and start the local stack
  .\dev.ps1 down           Stop containers (keeps volumes)
  .\dev.ps1 logs           Follow service logs
  .\dev.ps1 ps             Show service health
  .\dev.ps1 build          Build API and worker images
  .\dev.ps1 infra-install  Install CDK dependencies
  .\dev.ps1 infra-check    Type-check CDK
  .\dev.ps1 infra-synth    Synthesize CloudFormation
"@
    }
}

