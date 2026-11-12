// DA Registry (OpenG2P) -- CI/CD pipeline.
//
// Every branch: build the five images and push them to ECR.
// develop:      package helm/openg2p-da-registry with these images, deploy that archive to the dev
//               cluster (an upgrade of the existing release `da-registry` in namespace `da-registry`
//               with the public values pinned in ci/deploy/oan-chart.json and `--reset-values`; never
//               an install or an uninstall), then publish the same archive to repository/develop/ of
//               oan-helm. If the upgrade or the rollout fails, diagnostics are saved, the release is
//               rolled back to the last deployed revision and nothing is published.
// main:         build and push only; no deploy target yet.
// staging has its own pipeline, ci/pipelines/staging.groovy: it builds nothing and promotes.
def call() {
    pipeline {
        // The agent that reaches the dev cluster (as the livestock pipeline uses).
        agent { label 'oan-ci-deploy' }

        options {
            // Overlapping runs collide on the helm upgrade ("another operation in progress").
            disableConcurrentBuilds()
            // Agents are on-demand machines: if one is lost mid-build, run the build again.
            retry(count: 2, conditions: [agent(), nonresumable()])
        }

        environment {
            AWS_ACCOUNT_ID = "379220350808"
            AWS_REGION     = "ap-south-1"
            ECR_REGISTRY   = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
            // One ECR repository per component: openg2p/da-registry/<component>.
            ECR_BASE       = "openg2p/da-registry"

            // Must match ARG RP_VERSION in the component Dockerfiles
            // and "platformVersion" in ci/deploy/oan-chart.json (the pinned chart's openg2p-registry).
            // The staff UI is built from the same registry-platform run.
            RP_VERSION     = "1.2.2-rc.614"

            // Dev deployment. The chart, its version, the public values, the release and
            // the namespace are all read from ci/deploy/oan-chart.json by ci/deploy-dev.sh.
            // Kubeconfig (Jenkins "Secret file") for ServiceAccount da-registry-ci, which can
            // act in namespace da-registry only (k8s/da-registry-newdev-rbac.yaml).
            DEV_KUBECONFIG_CRED_ID = "da-registry-newdev-kubeconfig"
            // Stage 'Publish chart': a maintainer's token for now; the GitHub App replaces this credential when it is configured.
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
                    // Sample-approver password hook against a fake Keycloak (stdlib only, no network).
                    sh 'python3 -m unittest discover -s test -p test_sample_approver_password.py -v'
                    // Sample loader (sign-in, approvals, retries) against stand-ins, no cluster: pytest in the
                    // pinned Python image the chart's hook Jobs use, before the db-seed image is built.
                    sh 'docker run --rm -v "$PWD:/work:ro" -w /work python:3.11.14-slim sh -c "pip install -q --root-user-action=ignore --disable-pip-version-check pytest==8.3.4 && python -B -m pytest -q -p no:cacheprovider test/test_sample_loader.py"'
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

                        // The ECR digest of each image, for the stage 'Package chart': read from the
                        // push output, so no extra AWS permission is needed. component<TAB>sha256:...
                        sh 'mkdir -p .build && rm -f .build/image-digests.tsv'

                        // Each environment branch also moves a tag of its own name.
                        def movingTag = (env.BRANCH_NAME in ['develop', 'staging', 'main']) ? env.BRANCH_NAME : null
                        components.each { c ->
                            def image  = "${ECR_REGISTRY}/${ECR_BASE}/${c.name}:${env.IMAGE_TAG}"
                            def latest = movingTag ? "${ECR_REGISTRY}/${ECR_BASE}/${c.name}:${movingTag}" : null
                            // On-demand agents start with an empty Docker cache: reuse layers from the branch
                            // tag in ECR (develop for other branches), which carries inline cache metadata.
                            def cacheFrom = "${ECR_REGISTRY}/${ECR_BASE}/${c.name}:${movingTag ?: 'develop'}"
                            sh """
                                docker build --build-arg BUILDKIT_INLINE_CACHE=1 --cache-from ${cacheFrom} ${c.args} \
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

            stage('Package chart') {
                // helm/openg2p-da-registry with this build's images. The deploy installs this archive and
                // 'Publish chart' publishes the same one, so what runs on New Dev is what oan-helm lists.
                when { branch 'develop' }
                options { timeout(time: 15, unit: 'MINUTES') }
                steps {
                    sh 'bash ci/deploy/package-chart.sh'
                }
            }

            stage('Deploy to Development') {
                // Upgrades the existing release only (no --install), so a wrong
                // name or namespace fails instead of creating a second release.
                // ci/deploy-dev.sh takes the archive of 'Package chart' and the pinned public values,
                // renders them with this commit's images, and runs `helm upgrade
                // --reset-values`. On a failed upgrade or rollout it saves pods, events and
                // logs (deploy-failure-<build>.txt), then rolls back to the last deployed revision.
                when { branch 'develop' }
                steps {
                    withCredentials([file(credentialsId: "${DEV_KUBECONFIG_CRED_ID}", variable: 'KUBECONFIG')]) {
                        sh 'BUILT_CHART_DIR="$PWD/built-chart" bash ci/deploy-dev.sh "${IMAGE_TAG}"'
                    }
                }
                post {
                    always {
                        archiveArtifacts artifacts: 'dev-values-before-*.yaml, dev-rendered-*.yaml, deploy-failure-*.txt', allowEmptyArchive: true
                    }
                }
            }

            stage('Publish chart') {
                // The last stage. After a successful deploy (a failed deploy is rolled back and fails the build, so this
                // stage never runs for it): add the archive of 'Package chart' to repository/develop/ of oan-helm. Its
                // workflow updates the index, changelog and rollback history. If publishing fails the stage is UNSTABLE
                // and says why; New Dev already runs the build.
                when { branch 'develop' }
                options { timeout(time: 15, unit: 'MINUTES') }
                steps {
                    catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                        withCredentials([usernamePassword(credentialsId: "${OAN_HELM_FORK_CRED_ID}", usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')]) {
                            sh 'bash ci/deploy/publish-chart.sh'
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
}
return this
