// DA Registry (OpenG2P) -- CI/CD pipeline.
//
// Every branch: build the five images and push them to ECR.
// develop:      deploy them to the dev cluster, every build, no button: an upgrade of the
//               existing release `da-registry` in namespace `da-registry`, with the chart archive
//               and public values pinned in ci/deploy/oan-chart.json (oan-helm, verified by
//               SHA-256) and `--reset-values`. Never an install, never an uninstall. If the
//               upgrade or the rollout fails, diagnostics are saved and the release is rolled
//               back to the last revision that was deployed. Then two stages open pull requests into
//               oan-helm and never fail the build: one when oan-helm main has a newer chart or changed values
//               (the chart pin), and, last, one that records this build's image tags and digests in the oan-helm
//               DA chart (from the fork of oan-helm, ci/deploy/release_images.py). A person merges them.
// staging/main: build and push only; no deploy target yet.
pipeline {
    // The agent that reaches the dev cluster (as the livestock pipeline uses).
    agent { label 'vpn-agent2' }

    options {
        // Overlapping runs collide on the helm upgrade ("another operation in progress").
        disableConcurrentBuilds()
    }

    environment {
        AWS_ACCOUNT_ID = "379220350808"
        AWS_REGION     = "ap-south-1"
        ECR_REGISTRY   = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
        // One ECR repository for all components; the component is the tag
        // prefix (staff-api-<commit>, staff-api-develop, ...).
        ECR_REPO       = "openg2p/da-registry"

        // Must match ARG RP_VERSION in the component Dockerfiles
        // and "platformVersion" in ci/deploy/oan-chart.json (the pinned chart's openg2p-registry).
        // The staff UI is built from the same registry-platform run.
        RP_VERSION     = "1.2.2-rc.614"

        // Dev deployment. The chart, its version, the public values, the release and
        // the namespace are all read from ci/deploy/oan-chart.json by ci/deploy-dev.sh.
        // Kubeconfig (Jenkins "Secret file") for ServiceAccount da-registry-ci, which can
        // act in namespace da-registry only (k8s/da-registry-newdev-rbac.yaml).
        DEV_KUBECONFIG_CRED_ID = "da-registry-newdev-kubeconfig"
        // Used only by the last stage, to open a chart-pin pull request: a Jenkins GitHub App
        // (or "Username with password") credential with Contents and Pull requests write on this repository.
        PIN_PR_CRED_ID = "oan-ci-app"
        // Used only by the very last stage: "Username with password" = the GitHub account that owns the fork of oan-helm
        // and its classic token (public_repo). The image pull request goes from that fork into oan-helm main.
        OAN_HELM_FORK_CRED_ID = "oan-helm-fork-token"
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Validate chart pin') {
            // The pinned-chart consumer is checked on every build, pull requests
            // included: no network, no cluster.
            steps {
                sh 'docker run --rm --network none --entrypoint python -v "$PWD:/work:ro" -w /work openg2p/openg2p-registry-staff-api:${RP_VERSION} -m unittest discover -s test -p test_oan_chart.py -v'
            }
        }

        stage('Check deploy script') {
            // Rollback behaviour and the pin updater, with stand-in helm/kubectl:
            // no network, no cluster.
            steps {
                sh 'python3 -m unittest discover -s test -p "test_deploy_ci.py" -v'
            }
        }

        stage('ECR Login') {
            environment { DOCKER_CONFIG = "${env.WORKSPACE}/.docker-${env.BUILD_TAG}" }
            steps {
                withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'aws-ecr-creds']]) {
                    // Keep the buildx/compose CLI plugins visible from the per-build config dir.
                    sh 'mkdir -p "$DOCKER_CONFIG"; chmod 700 "$DOCKER_CONFIG"; if [ -d "$HOME/.docker/cli-plugins" ]; then ln -sfn "$HOME/.docker/cli-plugins" "$DOCKER_CONFIG/cli-plugins"; fi'
                    sh "aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_REGISTRY}"
                }
            }
        }

        stage('Build & Push') {
            environment { DOCKER_CONFIG = "${env.WORKSPACE}/.docker-${env.BUILD_TAG}" }
            steps {
                script {
                    env.IMAGE_TAG = env.GIT_COMMIT.take(12)

                    // Build the same component Dockerfiles that docker compose
                    // uses, so CI ships what developers run.
                    def components = [
                        [name: 'staff-api',   dockerfile: 'docker/staff-api/Dockerfile',   args: "--build-arg RP_VERSION=${RP_VERSION}"],
                        [name: 'staff-ui',    dockerfile: 'docker/staff-ui/Dockerfile',    args: ""],
                        [name: 'partner-api', dockerfile: 'docker/partner-api/Dockerfile', args: "--build-arg RP_VERSION=${RP_VERSION}"],
                        [name: 'celery',      dockerfile: 'docker/celery/Dockerfile',      args: "--build-arg RP_VERSION=${RP_VERSION}"],
                        [name: 'db-seed',     dockerfile: 'docker/db-seed/Dockerfile',     args: "--build-arg RP_VERSION=${RP_VERSION}"],
                    ]

                    // The ECR digest of each image, for the oan-helm image pull request (last stage): read from the
                    // push output, so no extra AWS permission is needed. component<TAB>sha256:...
                    sh 'mkdir -p .build && rm -f .build/image-digests.tsv .build/oan-helm-pr.txt'

                    // Each environment branch also moves a tag of its own name.
                    def movingTag = (env.BRANCH_NAME in ['develop', 'staging', 'main']) ? env.BRANCH_NAME : null
                    components.each { c ->
                        def image  = "${ECR_REGISTRY}/${ECR_REPO}:${c.name}-${env.IMAGE_TAG}"
                        def latest = movingTag ? "${ECR_REGISTRY}/${ECR_REPO}:${c.name}-${movingTag}" : null
                        sh """
                            docker build ${c.args} \
                                -f ${c.dockerfile} -t ${image} ${latest ? "-t ${latest}" : ''} .
                            docker push ${image} > .build/push-${c.name}.log 2>&1 || { cat .build/push-${c.name}.log; exit 1; }
                            cat .build/push-${c.name}.log
                            d=\$(grep -oE 'digest: sha256:[0-9a-f]{64}' .build/push-${c.name}.log | tail -n 1 | cut -d' ' -f2)
                            case "\$d" in sha256:*) ;; *) echo "no digest in the push output of ${c.name}" >&2; exit 1 ;; esac
                            printf '%s\\t%s\\n' "${c.name}" "\$d" >> .build/image-digests.tsv
                            ${latest ? "docker push ${latest}" : ''}
                        """
                    }
                }
            }
        }

        stage('Deploy to Development') {
            // Upgrades the existing release only (no --install), so a wrong
            // name or namespace fails instead of creating a second release.
            // ci/deploy-dev.sh verifies the pinned chart archive and public values,
            // renders them with this commit's images, and runs `helm upgrade
            // --reset-values`. On a failed upgrade or rollout it saves pods, events and
            // logs (deploy-failure-<build>.txt), then rolls back to the last deployed revision.
            when { branch 'develop' }
            steps {
                withCredentials([file(credentialsId: "${DEV_KUBECONFIG_CRED_ID}", variable: 'KUBECONFIG')]) {
                    sh 'bash ci/deploy-dev.sh "${IMAGE_TAG}"'
                }
            }
            post {
                always {
                    archiveArtifacts artifacts: 'dev-values-before-*.yaml, dev-rendered-*.yaml, deploy-failure-*.txt', allowEmptyArchive: true
                }
            }
        }

        stage('Propose chart pin update') {
            // After a successful build and deploy: compare the pinned oan-helm chart and public
            // values with oan-helm main and, when they differ, open a pull request that moves the
            // pin (ci/deploy/propose_pin_pr.py). A person merges it; the merge deploys. This stage
            // never deploys and never fails the build: if the credential is missing or GitHub
            // refuses, the stage turns UNSTABLE and says why.
            when { branch 'develop' }
            steps {
                catchError(buildResult: 'SUCCESS', stageResult: 'UNSTABLE') {
                    sh 'python3 ci/deploy/bump_pin.py --latest'
                    withCredentials([usernamePassword(credentialsId: "${PIN_PR_CRED_ID}", usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')]) {
                        sh 'python3 ci/deploy/propose_pin_pr.py'
                    }
                }
            }
        }

        stage('Open oan-helm image PR') {
            // The last stage. After the images were pushed AND deployed to New Dev (a failed deploy is rolled back and fails
            // the build, so this stage never runs for it): put this build's image repository, tags and digests into the
            // oan-helm DA chart (charts/openg2p-da-registry/values.yaml) through a pull request from the fork of oan-helm
            // (GH_USER/oan-helm) into Centre-for-Open-Societal-Systems/oan-helm main (ci/deploy/release_images.py). The
            // stage does not wait for the merge and ends green once the pull request is open; a person with write access
            // merges it and oan-helm's release workflow then publishes the chart and updates CHANGELOG.md. If the pull
            // request cannot be opened the stage is UNSTABLE and says why. One pull request per commit merged to develop:
            // a re-run of a commit that oan-helm main already carries opens nothing.
            when { branch 'develop' }
            options { timeout(time: 15, unit: 'MINUTES') }
            steps {
                script {
                    def subject = sh(returnStdout: true, script: 'git log -1 --pretty=%s').trim()
                    catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                        withCredentials([usernamePassword(credentialsId: "${OAN_HELM_FORK_CRED_ID}", usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')]) {
                            withEnv(["COMMIT_SUBJECT=${subject}", "SOURCE_COMMIT=${env.GIT_COMMIT}"]) {
                                sh 'python3 ci/deploy/release_images.py'
                            }
                        }
                    }
                }
            }
        }
    }

    post {
        failure {
            echo "DA registry ${env.BRANCH_NAME} build/deploy failed. A failed deploy is rolled back automatically; see the archived deploy-failure-${env.BUILD_NUMBER}.txt and 'helm history da-registry -n da-registry'."
        }
        always {
            sh 'docker image prune -f || true'
            sh 'rm -rf "${WORKSPACE}/.docker-${BUILD_TAG}"'
        }
    }
}
