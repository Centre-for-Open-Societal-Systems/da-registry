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
            // Every image: eoan/da-registry/<component>-<RP version>:<version>-<branch>.<build>, named by
            // ci/image_names.py (version from init.yaml, RP version from helm/openg2p-da-registry/Chart.yaml).

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
                // ci/validate.sh, the checks GitHub runs too: every test in test/ (rollback behaviour and the pin
                // updater with stand-in helm/kubectl, image names and ECR settings, the sample-approver hook, the
                // reporting views, the sample loader), with no network or cluster. In the pinned Python image the
                // chart's hook Jobs use, before any image is built.
                steps {
                    sh 'docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v "$PWD:/work:ro" -w /work python:3.11.14-slim sh -c "pip install -q --root-user-action=ignore --disable-pip-version-check pytest==8.4.2 ruff==0.17.2 PyYAML==6.0.2 && bash ci/validate.sh"'
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
                        env.IMAGE_TAG = sh(returnStdout: true,
                            script: 'python3 ci/image_names.py tag "$BRANCH_NAME" "$BUILD_NUMBER"').trim()

                        // Build the same component Dockerfiles that docker compose
                        // uses, so CI ships what developers run.
                        def components = [
                            [name: 'staff-api',   dockerfile: 'docker/staff-api/Dockerfile',   args: "--build-arg RP_VERSION=${RP_VERSION}"],
                            [name: 'staff-ui',    dockerfile: 'docker/staff-ui/Dockerfile',    args: ""],
                            [name: 'partner-api', dockerfile: 'docker/partner-api/Dockerfile', args: "--build-arg RP_VERSION=${RP_VERSION}"],
                            [name: 'celery',      dockerfile: 'docker/celery/Dockerfile',      args: "--build-arg RP_VERSION=${RP_VERSION}"],
                            [name: 'db-seed',     dockerfile: 'docker/db-seed/Dockerfile',     args: "--build-arg RP_VERSION=${RP_VERSION}"],
                            [name: 'sanity-tests', dockerfile: 'docker/sanity-tests/Dockerfile', args: "--build-arg RP_VERSION=${RP_VERSION}"],
                        ]

                        // The ECR digest of each image, for the stage 'Package chart': read from the
                        // push output, so no extra AWS permission is needed. component<TAB>repository<TAB>sha256:...
                        sh 'mkdir -p .build && rm -f .build/image-digests.tsv'

                        // ECR does not create repositories on push, a new platform version is a new repository name, and
                        // every eoan repository has immutable tags, scan on push, AES256 and the owner and naming tags:
                        // ci/ecr_repository.py creates a missing one and corrects an existing one, printing each change.
                        // Tags are immutable, so a version is pushed once and there is no moving tag (no <branch> tag).
                        components.each { c ->
                            def repository = sh(returnStdout: true, script: "python3 ci/image_names.py repository ${c.name}").trim()
                            def legacy = sh(returnStdout: true, script: "python3 ci/image_names.py legacy ${c.name}").trim()
                            def image  = "${ECR_REGISTRY}/${repository}:${env.IMAGE_TAG}"
                            withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'aws-ecr-creds']]) {
                                sh "python3 ci/ecr_repository.py ensure ${repository} ${legacy}"
                            }
                            sh """
                                docker build ${c.args} -f ${c.dockerfile} -t ${image} .
                                docker push ${image} > .build/push-${c.name}.log 2>&1 || { cat .build/push-${c.name}.log; exit 1; }
                                cat .build/push-${c.name}.log
                                d=\$(grep -oE 'digest: sha256:[0-9a-f]{64}' .build/push-${c.name}.log | tail -n 1 | cut -d' ' -f2)
                                case "\$d" in sha256:*) ;; *) echo "no digest in the push output of ${c.name}" >&2; exit 1 ;; esac
                                printf '%s\\t%s\\t%s\\n' "${c.name}" "${repository}" "\$d" >> .build/image-digests.tsv
                            """
                        }
                    }
                }
            }

            stage('Checks green') {
                // Nothing reaches New Dev unless every GitHub check of this commit passed (ci/deploy/require-green-checks.sh).
                // The images were built meanwhile; a red or still-pending commit stops here.
                when { allOf { branch 'develop'; not { changeRequest() } } }
                steps {
                    withCredentials([usernamePassword(credentialsId: "${OAN_HELM_FORK_CRED_ID}", usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')]) {
                        sh 'bash ci/deploy/require-green-checks.sh Centre-for-Open-Societal-Systems/da-registry "$(git rev-parse --verify HEAD)"'
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
                script {
                    // Mail the DevOps list and the commit author, as Farmer's pipelines do; a controller without SMTP
                    // must not hide the failure.
                    try {
                        def author = ''
                        try { author = sh(script: "git log -1 --pretty=format:'%ae'", returnStdout: true).trim() } catch (ignored) { author = '' }
                        def recipients = ['simretyibeltal@gmail.com', 'pavanns.ns@gmail.com']
                        if (author && !author.contains('noreply')) { recipients = [author] + recipients }
                        mail(
                            to: recipients.unique().join(', '),
                            subject: "Build FAILED: ${env.JOB_NAME} #${env.BUILD_NUMBER}",
                            body: "DA Registry develop build or deploy failed.\n\nJob:     ${env.JOB_NAME}\nBranch:  ${env.BRANCH_NAME}\nBuild:   #${env.BUILD_NUMBER}\nURL:     ${env.BUILD_URL}\nConsole: ${env.BUILD_URL}console\n\nJenkins"
                        )
                    } catch (err) {
                        echo "notification not sent: ${err.message}"
                    }
                }
            }
            always {
                sh 'docker image prune -f || true'
                sh 'rm -rf "${WORKSPACE}/.docker-${BUILD_TAG}"'
            }
        }
    }
}
return this
