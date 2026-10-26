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

        // Must match ARG RP_VERSION / STAFF_UI_VERSION in the root Dockerfile
        // and the openg2p-registry dependency in helm/openg2p-da-registry/Chart.yaml.
        // The staff UI is built from the same registry-platform run.
        RP_VERSION     = "1.2.2-rc.544"

        // New dev sandbox (development.oanstaging.com). The chart is the
        // published, immutable archive from the COSS oan-helm repository,
        // downloaded and checked against HELM_CHART_SHA256 before every deploy.
        // A newer chart is a reviewed change here: bump both lines together.
        OAN_HELM_RAW         = "https://raw.githubusercontent.com/Centre-for-Open-Societal-Systems/oan-helm/main"
        HELM_CHART_NAME      = "openg2p-da-registry"
        HELM_CHART_VERSION   = "1.0.0-dev.6"
        HELM_CHART_SHA256    = "1be5a9cd869340fb2fcb54e895aae0db480da8fb83129c3d23ad16455767e017"
        DEV_RELEASE          = "da-registry"
        DEV_NAMESPACE        = "da-registry"
        // Value layers, lowest first: oan-helm dev defaults, this repo's
        // DA values (images/enable flags), this repo's new-dev hostnames,
        // then the commit's image tags generated below.
        DEV_ENV_VALUES_URL   = "${OAN_HELM_RAW}/environments/dev/values/da.yaml"
        DEV_VALUES           = "deploy/dev/values-da.yaml"
        DEV_OVERLAY          = "deploy/dev/values-newdev.yaml"
        // Kubeconfig (Jenkins "Secret file") of the da-registry-ci ServiceAccount.
        DEV_KUBECONFIG_CRED_ID = "da-registry-newdev-kubeconfig"
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
                        def image  = "${ECR_REGISTRY}/${ECR_REPO}:${c.name}-${env.IMAGE_TAG}"
                        def latest = movingTag ? "${ECR_REGISTRY}/${ECR_REPO}:${c.name}-${movingTag}" : null
                        sh """
                            docker build ${c.args} --target ${c.target} \
                                -f Dockerfile -t ${image} ${latest ? "-t ${latest}" : ''} .
                            docker push ${image}
                            ${latest ? "docker push ${latest}" : ''}
                        """
                    }
                }
            }
        }

        stage('Deploy to Development') {
            // Installs or upgrades release `da-registry` in namespace `da-registry`
            // with the verified chart archive and this commit's images (by commit
            // tag, never by the moving -develop tag).
            //
            // Rollback: the upgrade is not --atomic, so a failure can be
            // inspected first. When the upgrade or a rollout check fails, the
            // pods/events/job logs are saved to deploy-failure-<build>.txt and the
            // release is rolled back to the last revision that was `deployed`,
            // then the build fails. On a first install there is nothing to roll
            // back to; the failed release is left in place to debug.
            when { branch 'develop' }
            steps {
                withCredentials([file(credentialsId: "${DEV_KUBECONFIG_CRED_ID}", variable: 'KUBECONFIG')]) {
                    sh '''
                        set -eu
                        WORK=.build
                        mkdir -p "$WORK"
                        CHART="$WORK/${HELM_CHART_NAME}-${HELM_CHART_VERSION}.tgz"

                        # Pinned chart archive, verified.
                        curl -fsSL -o "$CHART" "${OAN_HELM_RAW}/repository/${HELM_CHART_NAME}-${HELM_CHART_VERSION}.tgz"
                        echo "${HELM_CHART_SHA256}  $CHART" | sha256sum -c -

                        # oan-helm dev defaults (Keycloak, commons services, gateway).
                        curl -fsSL -o "$WORK/da-env.yaml" "$DEV_ENV_VALUES_URL"

                        # Image tags for this commit.
                        cat > "$WORK/images.yaml" <<EOF
registry:
  staffApi:
    image:
      tag: "staff-api-${IMAGE_TAG}"
  partnerApi:
    image:
      tag: "partner-api-${IMAGE_TAG}"
  celeryWorker:
    image:
      tag: "celery-${IMAGE_TAG}"
  celeryBeat:
    image:
      tag: "celery-${IMAGE_TAG}"
  staffUi:
    image:
      tag: "staff-ui-${IMAGE_TAG}"
  dbSeed:
    image:
      tag: "db-seed-${IMAGE_TAG}"
EOF
                        VALS="-f $WORK/da-env.yaml -f $DEV_VALUES -f $DEV_OVERLAY -f $WORK/images.yaml"

                        # What is about to be applied, kept for audit.
                        helm template "$DEV_RELEASE" "$CHART" -n "$DEV_NAMESPACE" $VALS > "$WORK/rendered.yaml"

                        # Guards: new-dev hostnames present, every DA image on this commit.
                        grep -q 'da-registry.development.oanstaging.com' "$WORK/rendered.yaml"
                        if grep -E "openg2p/da-registry:[a-z-]+-(develop|staging|main)\\b" "$WORK/rendered.yaml"; then
                            echo "ERROR: a DA image is not pinned to commit ${IMAGE_TAG}" >&2
                            exit 1
                        fi
                        N=$(grep -cE "openg2p/da-registry:[a-z-]+-${IMAGE_TAG}\\b" "$WORK/rendered.yaml" || true)
                        [ "$N" -ge 6 ] || { echo "ERROR: expected >= 6 DA image refs on ${IMAGE_TAG}, found $N" >&2; exit 1; }

                        # Last good revision, if any, to roll back to.
                        PREV=""
                        if helm list -n "$DEV_NAMESPACE" --deployed -q --filter "^${DEV_RELEASE}\\$" | grep -qx "$DEV_RELEASE"; then
                            PREV=$(helm status "$DEV_RELEASE" -n "$DEV_NAMESPACE" -o json | sed -n 's/.*"version":\\([0-9][0-9]*\\).*/\\1/p' | head -1)
                            helm get values "$DEV_RELEASE" -n "$DEV_NAMESPACE" -a -o yaml > "$WORK/values-before.yaml"
                        fi
                        echo "Last deployed revision: ${PREV:-none (first install)}"

                        # Server-side dry run: catches RBAC, schema and admission errors first.
                        helm upgrade --install "$DEV_RELEASE" "$CHART" -n "$DEV_NAMESPACE" $VALS --dry-run=server > "$WORK/dryrun.txt"

                        diag() {
                            {
                                echo "== helm history"; helm history "$DEV_RELEASE" -n "$DEV_NAMESPACE" --max 5
                                echo "== pods"; kubectl get pods -n "$DEV_NAMESPACE" -o wide
                                echo "== pods not Running/Succeeded"; kubectl get pods -n "$DEV_NAMESPACE" --field-selector=status.phase!=Running,status.phase!=Succeeded
                                echo "== events"; kubectl get events -n "$DEV_NAMESPACE" --sort-by=.lastTimestamp | tail -40
                                for j in $(kubectl get jobs -n "$DEV_NAMESPACE" -o name); do
                                    echo "== logs $j"; kubectl logs -n "$DEV_NAMESPACE" "$j" --all-containers --tail=40 2>&1 || true
                                done
                            } > "deploy-failure-${BUILD_NUMBER}.txt" 2>&1 || true
                        }

                        set +e
                        helm upgrade --install "$DEV_RELEASE" "$CHART" -n "$DEV_NAMESPACE" $VALS --wait --timeout 15m
                        RC=$?
                        if [ "$RC" -eq 0 ]; then
                            for d in staff-portal-api staff-portal-ui partner-api celery-worker; do
                                kubectl rollout status "deployment/${DEV_RELEASE}-$d" -n "$DEV_NAMESPACE" --timeout=300s || RC=1
                            done
                        fi
                        set -e

                        if [ "$RC" -ne 0 ]; then
                            diag
                            if [ -n "$PREV" ]; then
                                echo "Deploy failed; rolling back to revision $PREV"
                                helm rollback "$DEV_RELEASE" "$PREV" -n "$DEV_NAMESPACE" --wait --timeout 10m
                                echo "Rolled back to revision $PREV"
                            else
                                echo "Deploy failed on first install; nothing to roll back to."
                            fi
                            exit 1
                        fi

                        helm status "$DEV_RELEASE" -n "$DEV_NAMESPACE"
                    '''
                }
            }
            post {
                always {
                    archiveArtifacts artifacts: '.build/rendered.yaml, .build/da-env.yaml, .build/images.yaml, .build/values-before.yaml, .build/dryrun.txt, deploy-failure-*.txt', allowEmptyArchive: true
                }
            }
        }
    }

    post {
        failure {
            echo "DA registry ${env.BRANCH_NAME} build/deploy failed. For a deploy failure see the archived deploy-failure-${env.BUILD_NUMBER}.txt; 'helm history ${env.DEV_RELEASE} -n ${env.DEV_NAMESPACE}' shows the release state."
        }
        always {
            sh 'docker image prune -f || true'
            sh "docker logout ${ECR_REGISTRY} || true"
        }
    }
}
