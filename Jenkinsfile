// gym_app_new_backend/Jenkinsfile
// Declarative Pipeline for Backend CI/CD
// Required Jenkins plugins: Pipeline, SSH Agent, Credentials Binding, AnsiColor
//
// Trigger: Configure a GitHub webhook on the backend repo to call the Jenkins
//   /github-webhook/ endpoint on every push. The `when { branch "production" }`
//   guards below ensure the Deploy stage only runs when a PR is merged into
//   production (no direct pushes — enforce this with branch protection rules).
//
// Jenkins Credentials to configure (Manage Jenkins → Credentials):
//   - VPS_SSH_KEY        : SSH private key (Kind: SSH Username with private key)
//   - DJANGO_SECRET_KEY  : Secret text (used only for test runs in CI)
//
// Jenkins Environment Variables to configure (Manage Jenkins → System → Global properties):
//   - VPS_HOST           : VPS IP address or hostname
//   - VPS_PORT           : SSH port (default: 22)
//   - VPS_USER           : SSH login username
//   - VPS_BACKEND_PATH   : Absolute path on VPS (e.g. /opt/gym/backend)
//   - PUBLIC_DOMAIN      : Your domain (e.g. fitssort.com)

pipeline {
    agent any

    options {
        ansiColor("xterm")
        timeout(time: 30, unit: "MINUTES")
        buildDiscarder(logRotator(numToKeepStr: "15"))
        disableConcurrentBuilds(abortPrevious: true)
    }

    environment {
        PYTHON_VERSION = "3.12"
        DOCKER_BUILDKIT = "1"
        COMPOSE_DOCKER_CLI_BUILD = "1"
    }

    stages {
        // ── Stage 1: Lint ─────────────────────────────────────────────────
        stage("Lint") {
            steps {
                echo "Running ruff lint and format checks..."
                sh """
                    python${PYTHON_VERSION} -m venv .ci-venv
                    . .ci-venv/bin/activate
                    pip install --quiet ruff==0.9.0
                    ruff check . --output-format=text
                    ruff format --check .
                    deactivate
                """
            }
            post {
                always {
                    sh "rm -rf .ci-venv || true"
                }
            }
        }

        // ── Stage 2: Test ─────────────────────────────────────────────────
        stage("Test") {
            environment {
                DJANGO_SECRET_KEY = credentials("DJANGO_SECRET_KEY")
                // Postgres and Redis are expected as sidecar services in the
                // Jenkins agent environment. Adjust host/port to match your
                // Jenkins Docker-in-Docker setup or shared test DB.
                DATABASE_URL = "postgres://postgres:postgres@localhost:5432/test_gym"
                REDIS_HOST = "localhost"
                REDIS_PORT = "6379"
                CELERY_BROKER_URL = "redis://localhost:6379/0"
                CELERY_RESULT_BACKEND = "redis://localhost:6379/1"
                DJANGO_SETTINGS_MODULE = "config.settings"
                ALLOWED_HOSTS = "localhost,127.0.0.1"
                PUBLIC_DOMAIN = "localhost"
                DEBUG = "true"
                SKIP_DB_BOOTSTRAP = "1"
            }
            steps {
                echo "Installing Python dependencies..."
                sh """
                    python${PYTHON_VERSION} -m venv .test-venv
                    . .test-venv/bin/activate
                    pip install --quiet -r requirements.txt
                    echo "Running Django system checks..."
                    python manage.py check
                    echo "Running Django tests..."
                    python manage.py test --verbosity=2
                    deactivate
                """
            }
            post {
                always {
                    sh "rm -rf .test-venv || true"
                }
            }
        }

        // ── Stage 3: Deploy ───────────────────────────────────────────────
        // Only runs on the production branch
        stage("Deploy") {
            when {
                branch "production"
                beforeAgent true
            }
            environment {
                VPS_HOST = "${env.VPS_HOST}"
                VPS_PORT = "${env.VPS_PORT ?: '22'}"
                VPS_USER = "${env.VPS_USER}"
                VPS_BACKEND_PATH = "${env.VPS_BACKEND_PATH}"
            }
            steps {
                echo "Deploying backend to VPS at ${VPS_HOST}..."
                sshagent(credentials: ["VPS_SSH_KEY"]) {
                    sh """
                        ssh -o StrictHostKeyChecking=no \
                            -o ConnectTimeout=30 \
                            -p ${VPS_PORT} \
                            ${VPS_USER}@${VPS_HOST} '
                            set -euo pipefail

                            echo "==> Pulling latest production code..."
                            cd "${VPS_BACKEND_PATH}"
                            git fetch origin production
                            git reset --hard origin/production

                            echo "==> Rebuilding and restarting backend services..."
                            docker compose -f docker-compose.prod.yml up \\
                                --build \\
                                --detach \\
                                --remove-orphans \\
                                --wait \\
                                --wait-timeout 120

                            echo "==> Pruning unused Docker objects..."
                            docker image prune -f

                            echo "==> Backend deployment complete."
                        '
                    """
                }
            }
        }
    }

    post {
        success {
            echo "Pipeline succeeded on branch: ${env.BRANCH_NAME}"
        }
        failure {
            echo "Pipeline FAILED on branch: ${env.BRANCH_NAME} — check the logs above."
        }
        cleanup {
            cleanWs()
        }
    }
}
