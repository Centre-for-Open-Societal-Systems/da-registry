// DA Registry (OpenG2P) -- build, push to ECR, deploy to the dev cluster.
//
//   develop  -> build + push -> deploy to dev   (release da-registry, namespace da)
//   other    -> build + push only
//
// Staging is not deployed by this pipeline yet. When it is, it will move the
// staging Deployments to the new images with kubectl set image (no helm
// upgrade), as the crop pipeline does.
//
// Shaped after the crop pipeline (cropsown-coss/Jenkinsfile): one linear
// pipeline, one Deploy stage pinned to the `vpn-agent2` node (the only node
// that reaches the dev API server) and no build parameters. The deploy is a
// script, not inline Groovy, so a deploy by hand is the same command:
//
//   KUBECONFIG=<kubeconfig> AWS_ACCOUNT_ID=<id> ./ci/deploy-da-dev.sh <image-tag>
//
// Jenkins must hold: the string credential AWS_ACCOUNT_ID, the AWS credential
// aws-ecr-creds (ECR push), the secret-file credential da-dev-kubeconfig (the
// da-ci service account of the dev cluster) and the vpn-agent2 node.
pipeline {
    agent any

    environment {
        AWS_REGION     = "ap-south-1"
        ECR_PATH       = "openg2p/da-registry"

        // Must match ARG RP_VERSION / STAFF_UI_VERSION in the root Dockerfile
        // and the openg2p-registry dependency in helm/openg2p-da-registry/Chart.yaml.
        // The staff UI is built from the same registry-platform run.
        RP_VERSION     = "1.2.2-rc.544"

        HELM_CHART_DIR = "helm/openg2p-da-registry"
        HELM_RELEASE   = "da-registry"
        HELM_NAMESPACE = "da"

        // How long helm may wait on the chart's post-upgrade hook Jobs (db-seed,
        // iam-register). Kept well inside the Deploy stage's 60-minute timeout,
        // so a failing hook is reported with its logs instead of being cut off.
        HELM_TIMEOUT   = "20m"
    }

    options {
        timestamps()
        buildDiscarder(logRotator(numToKeepStr: '30'))
        timeout(time: 150, unit: 'MINUTES')
        // Two deploys at once leave the release locked ("another operation is
        // in progress"); a second build waits for the first instead.
        disableConcurrentBuilds()
    }

    // develop polls for new commits; every other branch builds only when asked.
    triggers {
        pollSCM(env.BRANCH_NAME == 'develop' ? 'H/5 * * * *' : '')
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Build & Push') {
            steps {
                // AWS_ACCOUNT_ID is a credential, bound only where it is used, so
                // the log masks it there.
                withCredentials([
                    string(credentialsId: 'AWS_ACCOUNT_ID', variable: 'AWS_ACCOUNT_ID'),
                    [$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'aws-ecr-creds']
                ]) {
                    script {
                        env.ECR_REGISTRY = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
                        // checkout scm does not always export GIT_COMMIT; read the
                        // workspace revision when it is missing.
                        def commit = env.GIT_COMMIT ?: sh(returnStdout: true, script: 'git rev-parse HEAD').trim()
                        env.IMAGE_TAG = commit.take(12)

                        sh "aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_REGISTRY}"

                        // Build the root Dockerfile's targets, the same definition
                        // docker compose builds, so CI ships what developers run.
                        def components = [
                            [name: 'staff-api',   target: 'staff-api',   args: "--build-arg RP_VERSION=${RP_VERSION}"],
                            [name: 'staff-ui',    target: 'staff-ui',    args: "--build-arg STAFF_UI_VERSION=${RP_VERSION}"],
                            [name: 'partner-api', target: 'partner-api', args: "--build-arg RP_VERSION=${RP_VERSION}"],
                            [name: 'celery',      target: 'celery',      args: "--build-arg RP_VERSION=${RP_VERSION}"],
                            [name: 'db-seed',     target: 'db-seed',     args: "--build-arg RP_VERSION=${RP_VERSION}"],
                        ]

                        // Each environment branch also moves a tag of its own name.
                        def movingTag = (env.BRANCH_NAME in ['develop', 'staging', 'main']) ? env.BRANCH_NAME : null
                        components.each { c ->
                            def repo   = "${ECR_PATH}/${c.name}"
                            def image  = "${env.ECR_REGISTRY}/${repo}:${env.IMAGE_TAG}"
                            def latest = movingTag ? "${env.ECR_REGISTRY}/${repo}:${movingTag}" : null
                            sh """
                                docker build ${c.args} --target ${c.target} \
                                    -f Dockerfile -t ${image} ${latest ? "-t ${latest}" : ''} .

                                # ECR does not create repositories on push.
                                aws ecr describe-repositories --region ${AWS_REGION} \
                                    --repository-names ${repo} >/dev/null 2>&1 \
                                  || aws ecr create-repository --region ${AWS_REGION} \
                                        --repository-name ${repo} >/dev/null

                                docker push ${image}
                                ${latest ? "docker push ${latest}" : ''}
                            """
                        }

                        // An ECR pull token for the deploy node to write into the
                        // namespace's imagePullSecret (ECR tokens last 12 hours, and
                        // the cluster's own refresh has been seen to break). Only this
                        // agent has AWS credentials, so the token is minted here and
                        // carried to the deploy node in the stash below.
                        sh '''
                            umask 077
                            aws ecr get-login-password --region ${AWS_REGION} > .ecr-token
                            echo "${ECR_REGISTRY}" > .ecr-registry
                        '''
                    }
                }
            }
        }

        stage('Stash deploy') {
            // The deploy node needs the chart, the script and the pull token, not
            // the build context and not a checkout of its own: it deploys exactly
            // this commit without GitHub access.
            steps {
                stash name: 'deploy', includes: "ci/**,${HELM_CHART_DIR}/**,.ecr-token,.ecr-registry"
                // Stashed; keep the token out of the build agent's workspace.
                sh 'rm -f .ecr-token .ecr-registry'
            }
        }

        stage('Deploy') {
            // develop only. beforeAgent: decide before asking for vpn-agent2, so
            // a build of any other branch never waits on that node.
            when {
                beforeAgent true
                branch 'develop'
            }
            agent { label 'vpn-agent2' }
            options {
                // Bounded: an offline vpn-agent2 does not fail a build, it queues
                // it. 60 covers the wait for the node, helm's 20 minutes of hooks,
                // the rollout waits and the diagnostics on failure.
                timeout(time: 60, unit: 'MINUTES')
            }
            steps {
                // The workspace outlives builds, and nothing cleans a file this
                // commit deleted out of a stash-only checkout.
                sh 'rm -rf ci helm'
                unstash 'deploy'
                withCredentials([
                    string(credentialsId: 'AWS_ACCOUNT_ID', variable: 'AWS_ACCOUNT_ID'),
                    file(credentialsId: 'da-dev-kubeconfig', variable: 'KUBECONFIG')
                ]) {
                    // catchInterruptions: a deploy that outlives the stage timeout
                    // FAILS the build instead of ending it ABORTED (which reads as
                    // "someone pressed Stop" and skips the failure handling).
                    catchError(buildResult: 'FAILURE', stageResult: 'FAILURE', catchInterruptions: true) {
                        sh 'bash ci/deploy-da-dev.sh "${IMAGE_TAG}"'
                    }
                }
            }
        }
    }

    post {
        always {
            sh 'docker image prune -f || true'
            sh 'rm -f .ecr-token .ecr-registry'
            sh 'docker logout "${ECR_REGISTRY}" || true'
        }
    }
}
