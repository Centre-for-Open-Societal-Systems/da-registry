// The staging branch builds nothing. A merge into staging promotes the chart that develop built from this source tree
// (the same image digests, under an rc version), deploys it and publishes it. See scripts/ci/deliver_staging.sh of oan-helm.
// The build fails if develop never built this tree: staging only runs what New Dev ran first.
def call() {
    pipeline {
        agent { label 'vpn-agent2' }
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
            stage('Promote and deploy') {
                when { allOf { branch 'staging'; not { changeRequest() } } }
                steps {
                    checkout scm
                    script {
                    def credentials = [
                        file(credentialsId: 'staging-rke2-kubeconfig', variable: 'KUBECONFIG'),
                        [$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'aws-ecr-creds'],
                        usernamePassword(credentialsId: 'oan-helm-fork-token', usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')
                    ]
                    // The sample loader signs in as the sample staff users (alex.carter, nina.patel) with
                    // global.aweApproverUserPassword, which keycloak-init also sets as their password. The staging
                    // overlay leaves it empty, so it comes from this Jenkins Secret text, and only when sample data is asked for.
                    if (params.LOAD_SAMPLE_DATA) {
                        credentials << string(credentialsId: 'staging-sample-users-password', variable: 'SAMPLE_USERS_PASSWORD')
                    }
                    withCredentials(credentials) {
                        sh '''
                          set -eu
                          sample=''
                          if [ "${LOAD_SAMPLE_DATA:-false}" = true ]; then
                            if [ -z "${SAMPLE_USERS_PASSWORD:-}" ]; then
                              echo 'LOAD_SAMPLE_DATA needs the Jenkins credential staging-sample-users-password' >&2
                              exit 1
                            fi
                            # A private values file, so the password is never on a command line or in the log.
                            sample_values=$(umask 077 && mktemp)
                            trap 'rm -f "$sample_values"' EXIT
                            python3 -c 'import json, os, sys; json.dump({"global": {"aweApproverUserPassword": os.environ["SAMPLE_USERS_PASSWORD"]}}, open(sys.argv[1], "w"))' "$sample_values"
                            sample="--set registry.dbSeed.loadSampleData=true -f $sample_values"
                          fi
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
        }
    }
}
return this
