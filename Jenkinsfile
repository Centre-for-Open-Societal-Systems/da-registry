// DA Registry (OpenG2P) -- CI/CD pipeline.
//
// Every branch: build the five images and push them to ECR.
// develop:      also deploy them to the dev cluster, release `da` in namespace
//               `commons`, chart oan-coss/openg2p-da-registry (the one Rancher
//               installed). Values: deploy/dev/values-da.yaml.
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
        // and the openg2p-registry dependency in helm/openg2p-da-registry/Chart.yaml.
        // The staff UI is built from the same registry-platform run.
        RP_VERSION     = "1.2.2-rc.557"

        // Dev deployment. The chart and version are the ones the release was
        // installed with in Rancher; move them together with that install.
        HELM_CHART_REPO_NAME = "oan-coss"
        HELM_CHART_REPO_URL  = "https://raw.githubusercontent.com/Centre-for-Open-Societal-Systems/oan-helm/main/repository/"
        HELM_CHART           = "oan-coss/openg2p-da-registry"
        HELM_CHART_VERSION   = "1.0.0-dev.5"
        DEV_RELEASE          = "da"
        DEV_NAMESPACE        = "commons"
        DEV_VALUES           = "deploy/dev/values-da.yaml"
        // Kubeconfig (Jenkins "Secret file") allowed to upgrade the release in DEV_NAMESPACE.
        DEV_KUBECONFIG_CRED_ID = "da-dev-kubeconfig"
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
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
            // --reuse-values keeps what was set in Rancher; DEV_VALUES and the
            // commit's image tags go on top. No --atomic: a failing db-seed
            // hook should leave the release inspectable, not roll it back.
            when { branch 'develop' }
            steps {
                withCredentials([file(credentialsId: "${DEV_KUBECONFIG_CRED_ID}", variable: 'KUBECONFIG')]) {
                    sh """
                        set -eu
                        helm repo add ${HELM_CHART_REPO_NAME} ${HELM_CHART_REPO_URL} --force-update
                        helm repo update ${HELM_CHART_REPO_NAME}
                        helm status ${DEV_RELEASE} -n ${DEV_NAMESPACE} > /dev/null

                        IMAGE_SET_FLAGS="
                            --set-string registry.staffApi.image.tag=staff-api-${IMAGE_TAG}
                            --set-string registry.partnerApi.image.tag=partner-api-${IMAGE_TAG}
                            --set-string registry.celeryWorker.image.tag=celery-${IMAGE_TAG}
                            --set-string registry.celeryBeat.image.tag=celery-${IMAGE_TAG}
                            --set-string registry.staffUi.image.tag=staff-ui-${IMAGE_TAG}
                            --set-string registry.dbSeed.image.tag=db-seed-${IMAGE_TAG}
                        "

                        # Values before, and the manifests about to be applied, kept for audit.
                        helm get values ${DEV_RELEASE} -n ${DEV_NAMESPACE} -a -o yaml > dev-values-before-${BUILD_NUMBER}.yaml
                        helm template ${DEV_RELEASE} ${HELM_CHART} --version ${HELM_CHART_VERSION} -n ${DEV_NAMESPACE} \
                            -f dev-values-before-${BUILD_NUMBER}.yaml -f ${DEV_VALUES} \$IMAGE_SET_FLAGS \
                            > dev-rendered-${BUILD_NUMBER}.yaml

                        helm upgrade ${DEV_RELEASE} ${HELM_CHART} --version ${HELM_CHART_VERSION} -n ${DEV_NAMESPACE} \
                            --reuse-values -f ${DEV_VALUES} \$IMAGE_SET_FLAGS \
                            --cleanup-on-fail --timeout 15m

                        for d in staff-portal-api staff-portal-ui partner-api; do
                            kubectl rollout status deployment/${DEV_RELEASE}-\$d -n ${DEV_NAMESPACE} --timeout=300s
                        done
                    """
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
            echo "DA registry ${env.BRANCH_NAME} build/deploy failed. For a deploy failure, 'helm history ${env.DEV_RELEASE} -n ${env.DEV_NAMESPACE}' shows the release state."
        }
        always {
            sh 'docker image prune -f || true'
            sh "docker logout ${ECR_REGISTRY} || true"
        }
    }
}
