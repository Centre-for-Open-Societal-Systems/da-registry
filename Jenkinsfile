// DA Registry (OpenG2P) -- CI/CD pipeline.
//
// Every branch: build the five images and push them to ECR.
// develop:      deploy them to the dev cluster only when DEPLOY_TO_DEV is ticked: an upgrade of the
//               existing release `da-registry` in namespace `da-registry`, with the chart archive
//               and public values pinned in ci/deploy/oan-chart.json (oan-helm, verified by
//               SHA-256) and `--reset-values`. Never an install, never an uninstall.
// staging/main: build and push only; no deploy target yet.
pipeline {
    // The agent that reaches the dev cluster (as the livestock pipeline uses).
    agent { label 'vpn-agent2' }

    options {
        // Overlapping runs collide on the helm upgrade ("another operation in progress").
        disableConcurrentBuilds()
    }

    parameters {
        // Off by default: a develop build only builds and pushes the images. The
        // dev deploy waits until the release target, the pinned values and the
        // Keycloak client secret the values reference exist; then a person ticks
        // this on a develop build.
        booleanParam(name: 'DEPLOY_TO_DEV', defaultValue: false,
                     description: 'Deploy this develop build to the dev cluster')
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
        // Kubeconfig (Jenkins "Secret file") allowed to upgrade the release in its namespace.
        DEV_KUBECONFIG_CRED_ID = "da-dev-kubeconfig"
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

        stage('ECR Login') {
            steps {
                withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'aws-ecr-creds']]) {
                    sh "aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_REGISTRY}"
                }
            }
        }

        stage('Build & Push') {
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

                    // Each environment branch also moves a tag of its own name.
                    def movingTag = (env.BRANCH_NAME in ['develop', 'staging', 'main']) ? env.BRANCH_NAME : null
                    components.each { c ->
                        def image  = "${ECR_REGISTRY}/${ECR_REPO}:${c.name}-${env.IMAGE_TAG}"
                        def latest = movingTag ? "${ECR_REGISTRY}/${ECR_REPO}:${c.name}-${movingTag}" : null
                        sh """
                            docker build ${c.args} \
                                -f ${c.dockerfile} -t ${image} ${latest ? "-t ${latest}" : ''} .
                            docker push ${image}
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
            // --reset-values`. No --atomic: a failing db-seed hook should leave the
            // release inspectable, not roll it back.
            when { allOf { branch 'develop'; expression { params.DEPLOY_TO_DEV } } }
            steps {
                withCredentials([file(credentialsId: "${DEV_KUBECONFIG_CRED_ID}", variable: 'KUBECONFIG')]) {
                    sh 'bash ci/deploy-dev.sh "${IMAGE_TAG}"'
                }
            }
            post {
                always {
                    archiveArtifacts artifacts: 'dev-values-before-*.yaml, dev-rendered-*.yaml', allowEmptyArchive: true
                }
            }
        }
    }

    post {
        failure {
            echo "DA registry ${env.BRANCH_NAME} build/deploy failed. For a deploy failure, 'helm history da-registry -n da-registry' shows the release state."
        }
        always {
            sh 'docker image prune -f || true'
            sh "docker logout ${ECR_REGISTRY} || true"
        }
    }
}
