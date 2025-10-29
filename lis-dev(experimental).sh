#!/bin/bash

# LIS Developer Environment Management Script
# This script helps manage the unified Docker Compose environment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_color() {
    color=$1
    message=$2
    echo -e "${color}${message}${NC}"
}

# Function to check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        print_color $RED "❌ Docker is not running. Please start Docker first."
        exit 1
    fi
}

# Function to check if .env file exists
check_env_file() {
    if [ ! -f .env ]; then
        print_color $YELLOW "⚠️ No .env file found. Creating from .env.example..."
        if [ -f .env.example ]; then
            cp .env.example .env
            
            # Set AIRFLOW_UID on Linux/macOS
            if [[ "$OSTYPE" == "linux-gnu"* ]] || [[ "$OSTYPE" == "darwin"* ]]; then
                echo "AIRFLOW_UID=$(id -u)" >> .env
                print_color $GREEN "✅ Set AIRFLOW_UID=$(id -u) in .env file"
            fi
            
            print_color $GREEN "✅ Created .env file from .env.example"
            print_color $YELLOW "⚠️ Please review and edit .env file if needed"
        else
            print_color $RED "❌ No .env.example file found"
            exit 1
        fi
    fi
}

# Function to create required directories
create_directories() {
    print_color $BLUE "📁 Creating required directories..."
    
    directories=(
        "airflow/dags"
        "airflow/logs" 
        "airflow/plugins"
        "airflow/config"
        "ciso/db"
        "ciso/caddy_data"
    )
    
    for dir in "${directories[@]}"; do
        if [ ! -d "$dir" ]; then
            mkdir -p "$dir"
            print_color $GREEN "✅ Created directory: $dir"
        fi
    done
}

# Function to fix permissions
fix_permissions() {
    print_color $BLUE "🔧 Fixing permissions..."
    
    # Fix Airflow permissions on Linux/macOS
    if [[ "$OSTYPE" == "linux-gnu"* ]] || [[ "$OSTYPE" == "darwin"* ]]; then
        if [ -d "airflow" ]; then
            chmod -R 755 airflow/
            print_color $GREEN "✅ Fixed Airflow directory permissions"
        fi
    fi
}

# Function to check service health
check_health() {
    print_color $BLUE "🏥 Checking service health..."
    
    # Check if containers are running
    running_containers=$(docker compose ps --services --filter "status=running" | wc -l)
    total_containers=$(docker compose ps --services | wc -l)
    
    print_color $GREEN "✅ Running containers: $running_containers/$total_containers"
    
    # Detailed health check
    echo ""
    print_color $BLUE "📊 Service Status:"
    docker compose ps
}

# Function to show service URLs
show_urls() {
    print_color $BLUE "🌐 Service URLs:"
    echo ""
    echo "🔧 Airflow Web UI:      http://localhost:8080"
    echo "   Username: airflow, Password: airflow"
    echo ""
    echo "🛡️  CISO Assistant:      https://localhost:8443"
    echo "   Email: email, Password: 1234"
    echo ""
    echo "📊 Redpanda Console:    http://localhost:8088"
    echo ""
    echo "🌸 Flower (optional):   http://localhost:5555"
    echo "   (only if started with --profile flower)"
    echo ""
    print_color $YELLOW "⚠️ Note: It may take a few minutes for all services to be fully ready"
}

# Function to start all services
start_all() {
    print_color $GREEN "🚀 Starting all LIS services..."
    docker compose up -d
    echo ""
    show_urls
}

# Function to start specific service groups
start_airflow() {
    print_color $GREEN "🚀 Starting Airflow services..."
    docker compose up -d postgres redis airflow-init airflow-apiserver airflow-scheduler airflow-worker airflow-triggerer airflow-dag-processor
}

start_ciso() {
    print_color $GREEN "🚀 Starting CISO Assistant services..."
    docker compose up -d ciso-backend ciso-huey ciso-frontend ciso-caddy
}

start_redpanda() {
    print_color $GREEN "🚀 Starting Redpanda services..."
    docker compose up -d redpanda-0 redpanda-console
}

start_ciso_with_kafka() {
    print_color $GREEN "🚀 Starting CISO Assistant with Kafka integration..."
    docker compose up -d redpanda-0 ciso-backend ciso-huey ciso-frontend ciso-caddy ciso-dispatcher
}

# Function to stop services
stop_all() {
    print_color $YELLOW "⏹️ Stopping all services..."
    docker compose down
}

# Function to restart services
restart_all() {
    print_color $YELLOW "🔄 Restarting all services..."
    docker compose down
    docker compose up -d
}

# Function to view logs
view_logs() {
    service=$1
    if [ -z "$service" ]; then
        print_color $BLUE "📋 Viewing logs for all services (Ctrl+C to exit):"
        docker compose logs -f
    else
        print_color $BLUE "📋 Viewing logs for $service (Ctrl+C to exit):"
        docker compose logs -f "$service"
    fi
}

# Function to reset everything
reset_all() {
    print_color $RED "⚠️ This will stop all services and remove all data!"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_color $YELLOW "🗑️ Removing all services and data..."
        docker compose down -v
        docker system prune -f
        print_color $GREEN "✅ Reset complete"
    else
        print_color $GREEN "✅ Reset cancelled"
    fi
}

# Function to show usage
usage() {
    echo "LIS Developer Environment Management Script"
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  setup                 Initialize environment (create dirs, fix permissions)"
    echo "  start                 Start all services"
    echo "  start-airflow         Start only Airflow services"
    echo "  start-ciso            Start only CISO Assistant services"
    echo "  start-redpanda        Start only Redpanda services"
    echo "  start-ciso-kafka      Start CISO Assistant with Kafka integration"
    echo "  stop                  Stop all services"
    echo "  restart               Restart all services"
    echo "  status                Show service status"
    echo "  health                Check service health"
    echo "  urls                  Show service URLs"
    echo "  logs [service]        View logs (all services if no service specified)"
    echo "  reset                 Reset everything (removes all data!)"
    echo "  flower                Start with Flower monitoring"
    echo "  debug                 Start with debug profile"
    echo ""
    echo "Examples:"
    echo "  $0 setup              # Initialize environment"
    echo "  $0 start              # Start all services"
    echo "  $0 logs airflow-apiserver  # View Airflow API server logs"
    echo "  $0 health             # Check if services are healthy"
}

# Main script logic
case "$1" in
    setup)
        check_docker
        check_env_file
        create_directories
        fix_permissions
        print_color $GREEN "✅ Environment setup complete!"
        print_color $BLUE "💡 Run '$0 start' to start all services"
        ;;
    start)
        check_docker
        check_env_file
        create_directories
        start_all
        ;;
    start-airflow)
        check_docker
        check_env_file
        create_directories
        start_airflow
        ;;
    start-ciso)
        check_docker
        check_env_file
        start_ciso
        ;;
    start-redpanda)
        check_docker
        check_env_file
        start_redpanda
        ;;
    start-ciso-kafka)
        check_docker
        check_env_file
        start_ciso_with_kafka
        ;;
    stop)
        check_docker
        stop_all
        ;;
    restart)
        check_docker
        restart_all
        ;;
    status)
        check_docker
        docker compose ps
        ;;
    health)
        check_docker
        check_health
        ;;
    urls)
        show_urls
        ;;
    logs)
        check_docker
        view_logs "$2"
        ;;
    reset)
        check_docker
        reset_all
        ;;
    flower)
        check_docker
        check_env_file
        create_directories
        print_color $GREEN "🚀 Starting all services with Flower monitoring..."
        docker compose --profile flower up -d
        show_urls
        ;;
    debug)
        check_docker
        check_env_file
        create_directories
        print_color $GREEN "🚀 Starting all services with debug profile..."
        docker compose --profile debug up -d
        show_urls
        ;;
    *)
        usage
        exit 1
        ;;
esac