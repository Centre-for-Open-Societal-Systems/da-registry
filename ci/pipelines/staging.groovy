// The staging branch builds nothing. A merge into staging promotes the chart that develop built from this source tree
// (the same image digests, under an rc version), deploys it and publishes it. See scripts/ci/deliver_staging.sh of oan-helm.
// The build fails if develop never built this tree: staging only runs what New Dev ran first.
def call() {
    pipeline {
        agent { label 'oan-ci-deploy' }
        options {
            timestamps()
            disableConcurrentBuilds()
            buildDiscarder(logRotator(numToKeepStr: '30'))
            timeout(time: 60, unit: 'MINUTES')
        }
        parameters {
            booleanParam(name: 'LOAD_SAMPLE_DATA', defaultValue: false,
                description: 'Load the sample records (db-seed hook) during this staging deploy. Leave off for a clean registry.')
        }
        stages {
            stage('Checks green') {
                // Nothing reaches staging unless every GitHub check of this commit passed (ci/deploy/require-green-checks.sh).
                when { allOf { branch 'staging'; not { changeRequest() } } }
                steps {
                    checkout scm
                    withCredentials([usernamePassword(credentialsId: 'oan-helm-fork-token', usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')]) {
                        sh 'bash ci/deploy/require-green-checks.sh Centre-for-Open-Societal-Systems/da-registry "$(git rev-parse --verify HEAD)"'
                    }
                }
            }
            stage('Promote and deploy') {
                when { allOf { branch 'staging'; not { changeRequest() } } }
                steps {
                    checkout scm
                    withCredentials([
                        file(credentialsId: 'staging-rke2-kubeconfig', variable: 'KUBECONFIG'),
                        [$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'aws-ecr-creds'],
                        usernamePassword(credentialsId: 'oan-helm-fork-token', usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')
                    ]) {
                        sh '''
                          set -eu
                          sample=''
                          if [ "${LOAD_SAMPLE_DATA:-false}" = true ]; then sample='--set registry.dbSeed.loadSampleData=true'; fi
                          rm -rf .oan-helm
                          git clone --quiet --depth 1 --filter=blob:none --sparse \\
                            https://github.com/Centre-for-Open-Societal-Systems/oan-helm.git .oan-helm
                          git -C .oan-helm sparse-checkout set scripts/ci environments/staging/values
                          bash .oan-helm/scripts/ci/deliver_staging.sh openg2p-da-registry da-registry da-registry da.yaml $sample
                        '''
                    }
                }
            }
        }
        post {
            failure {
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
                            body: "DA Registry staging promotion or deploy failed.\n\nJob:     ${env.JOB_NAME}\nBranch:  ${env.BRANCH_NAME}\nBuild:   #${env.BUILD_NUMBER}\nURL:     ${env.BUILD_URL}\nConsole: ${env.BUILD_URL}console\n\nJenkins"
                        )
                    } catch (err) {
                        echo "notification not sent: ${err.message}"
                    }
                }
            }
        }
    }
}
return this
